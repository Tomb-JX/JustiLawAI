"""Offline S0/coordinate/S3/element replay and parsed-2 development assembly.

Uses existing S1 responses; never instantiates an HTTP provider. Every output is a
new parsed2 candidate batch; no release decision, label publication or source edit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from cleanse import replay_edits
from element_contract import contract_snapshot, digest, validate_located
from durable_calls import read_rows
from run_elements import ENGINE, build_inputs, _candidates
from locate import OffsetIndex
from s1 import data_root
from s3 import run_checks, zone_spans
from freeze_slice import leak_reasons

VERSION = "pipeline-offline-v2"


def unique(rows):
    out = {}
    for row in rows:
        if row["id"] in out:
            raise ValueError(f"duplicate_id:{row['id']}")
        out[row["id"]] = row
    return out


def assemble(unified: Path, parsed: Path, run: Path, out: Path, *, elements: Path | None = None):
    if out.exists():
        raise FileExistsError("parsed2 批次不可复用")
    paths = [unified, parsed, unified.with_name("edits.rle.jsonl"), run / "outputs.jsonl"]
    fingerprints = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    raw, sources, edits, outputs = [unique(read_rows(p)) for p in paths]
    old = run / "elements"
    for p in [old / n for n in ("A.jsonl", "B.jsonl", "labels.jsonl")]:
        if p.exists():
            fingerprints[str(p.resolve())] = hashlib.sha256(p.read_bytes()).hexdigest()
    a, b, labels = [unique(read_rows(old / n)) for n in ("A.jsonl", "B.jsonl", "labels.jsonl")]
    records, findings, rejected, audit = [], [], [], []
    counters, element_counts = Counter(), Counter()
    for rid, response in outputs.items():
        if not response.get("ok"):
            rejected.append({"id": rid, "reason": "s1_failed"})
            counters["s1_failed"] += 1
            continue
        try:
            source, rec = sources[rid], dict(raw[rid])
            original = source["text_full"]
            if hashlib.sha256(original.encode("utf-8")).hexdigest() != rec["text_orig_sha256"]:
                raise ValueError("source_hash_mismatch")
            if replay_edits(original, edits[rid]) != rec["cleaned_text"]:
                raise ValueError("s0_replay_mismatch")
            index = OffsetIndex(edits[rid])
            spans = zone_spans(response["output"], rec["sentences"], index)
            checks = run_checks({"record": rec, "output": response["output"],
                                 "sentences": rec["sentences"], "spans": spans})
            status = "error" if any(f.severity == "error" for f in checks) else "warn" if checks else "pass"
            counters[status] += 1
            findings.append({"id": rid, "status": status, "form": rec["form"],
                             "findings": [f.as_dict() for f in checks]})
            rec["_text_full"] = original
            inp = build_inputs(rec, response["output"], index)
            if inp is None:
                raise ValueError("missing_target_or_input")
            if rid in labels:
                legacy = {"id": rid, "status": "quarantined", "issues": []}
                stored = labels[rid].get("input") or {}
                if any(stored.get(k) != inp[k] for k in ("target", "facts_text", "meta_text")):
                    legacy["issues"].append("historical_input_differs")
                for tag, pool in (("A", a), ("B", b)):
                    try:
                        _candidates(pool[rid]["elements"], original, tag, inp["regions"])
                    except (ValueError, KeyError, TypeError) as exc:
                        legacy["issues"].append(f"{tag}:{str(exc)[:350]}")
                try:
                    validate_located(labels[rid]["elements"], original, ENGINE, inp["regions"])
                except (ValueError, TypeError) as exc:
                    legacy["issues"].append(f"merged:{str(exc)[:350]}")
                # Even schema-clean legacy rows need independent review; no old label is promoted.
                legacy["requires_new_contract_review"] = True
                audit.append(legacy)
            if status == "error":
                rejected.append({"id": rid, "reason": "s3_error"})
                continue
            fact_flags = leak_reasons(inp["facts_text"])
            result = {"id": rid, "record_version": "parsed2-development-1",
                      "text_full": original, "text_orig_sha256": rec["text_orig_sha256"],
                      "subject_mention": inp["target"], "subject_aliases": inp["aliases"],
                      "facts_view": inp["sentence_view"], "view_hash": inp["view_hash"],
                      "text_facts": inp["facts_text"], "text_party": inp["meta_text"],
                      "zones": response["output"]["zones"],
                      "observed_outcome": response["output"]["outcome"],
                      "source_observed_outcome": source.get("outcome"),
                      "dates": response["output"].get("dates"),
                      "review": response["output"].get("review"),
                      "source_metadata": {k: source.get(k) for k in ("source", "batch", "event_key",
                                            "doc_no_hash", "region", "province", "law_version")},
                      "quality": {"s3_status": status, "fact_isolation_flags": fact_flags,
                                  "m1_input_candidate": not fact_flags},
                      "elements_status": "not_available", "release_approved": False,
                      "pipeline_version": VERSION, "s1_prompt_version": "seg-v2"}
            result["s1_confidence_diagnostic"] = response["output"].get("confidence")
            if elements:
                path = elements / f"record-{rid}.json"
                if path.exists():
                    label = json.loads(path.read_text("utf-8"))
                    if (label.get("status") != "valid" or label.get("view_hash") != inp["view_hash"]
                            or label.get("contract_hash") != digest(contract_snapshot(ENGINE))
                            or (label.get("input") or {}).get("text_orig_sha256") != rec["text_orig_sha256"]):
                        raise ValueError("element_commit_context_mismatch")
                    if any((label.get("input") or {}).get(k) != inp[k]
                           for k in ("target", "facts_text", "meta_text")):
                        raise ValueError("element_commit_input_mismatch")
                    validate_located(label["elements"], original, ENGINE, inp["regions"])
                    result.update({"elements": label["elements"], "elements_status": "candidate_validated",
                                   "element_schema_version": label["element_schema_version"],
                                   "element_prompt_version": label["element_prompt_version"],
                                   "label_provenance": "model-adjudicated", "human_review": False})
            element_counts[result["elements_status"]] += 1
            records.append(result)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            counters["input_or_contract_rejected"] += 1
            rejected.append({"id": rid, "reason": str(exc)[:350]})
    report = {"version": VERSION, "s1_selected": len(outputs), "s3_n": len(findings),
              "s3_status": {k: counters[k] for k in ("pass", "warn", "error")},
              "hard_failure_rate": counters["error"] / len(findings) if findings else None,
              "s1_failed": counters["s1_failed"], "parsed2_candidate_records": len(records),
              "input_or_contract_rejected": counters["input_or_contract_rejected"],
              "legacy_label_audited": len(audit), "legacy_labels_promoted": 0,
              "historical_input_differences": sum("historical_input_differs" in r["issues"] for r in audit),
              "element_states": dict(element_counts), "release_approved": False,
              "contract": contract_snapshot(ENGINE), "source_hashes": fingerprints}
    out.mkdir(parents=True, exist_ok=False)
    for name, rows in (("records.jsonl", records), ("s3-findings.jsonl", findings),
                       ("excluded.jsonl", rejected), ("legacy-element-audit.jsonl", audit)):
        with (out / name).open("x", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    report["artifact_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob("*.jsonl")}
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h for p, h in fingerprints.items()):
        raise RuntimeError("source_changed_during_replay")
    with (out / "summary.json").open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def main():
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--unified", type=Path, required=True)
    p.add_argument("--parsed", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--elements", type=Path)
    a = p.parse_args()
    if not a.out.resolve().is_relative_to((data_root() / "parsed2").resolve()):
        p.error("只写新的 $DATA/parsed2 子目录")
    print(json.dumps(assemble(a.unified, a.parsed, a.run, a.out, elements=a.elements),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

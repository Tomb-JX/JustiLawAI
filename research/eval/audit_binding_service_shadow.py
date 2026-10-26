"""Read-only admission audit for binding-service output; never creates training labels."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from normalization_spec import normalize_amount


FIELDS = {"amounts.personal_stake", "amounts.onsite_stake_total",
          "persons.participant_count", "person.age"}
AMOUNTS = {"amounts.personal_stake", "amounts.onsite_stake_total"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def person_id(source_sha256: str, target: str) -> str:
    return "P-" + hashlib.sha256(f"{source_sha256}|{target}".encode("utf-8")).hexdigest()[:16]


def audit_record(inp: dict, output: dict, manifest_sha256: str) -> list[str]:
    errors = []
    source = inp["text_full"]
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    view_hash = digest(inp["sentence_view"])
    target_id = person_id(source_hash, inp["target"])
    if source_hash != inp.get("source_sha256") or view_hash != inp.get("view_hash"):
        errors.append("input_source_or_view_hash_mismatch")
    if (output.get("id") != inp["id"] or output.get("target") != inp["target"]
            or output.get("target_id") != target_id
            or output.get("source_sha256") != source_hash or output.get("view_hash") != view_hash):
        errors.append("output_identity_or_provenance_mismatch")
    if output.get("service_version") != "binding-v1.1" or output.get("artifact_manifest_sha256") != manifest_sha256:
        errors.append("service_version_or_manifest_mismatch")
    bindings = output.get("bindings") or []
    if len(bindings) != 4 or {b.get("field") for b in bindings} != FIELDS:
        errors.append("field_set_mismatch")
    for binding in bindings:
        field = binding.get("field")
        if binding.get("target_id") != target_id:
            errors.append(f"{field}:target_id_mismatch")
        status = binding.get("binding_status")
        value = binding.get("value")
        cids = binding.get("candidate_ids") or []
        evidence = binding.get("evidence") or []
        if status not in {"bound", "unresolved"}:
            errors.append(f"{field}:invalid_status")
        if status == "unresolved" and (value is not None or not binding.get("reason")):
            errors.append(f"{field}:unresolved_value_or_reason")
        if status == "bound":
            if not evidence or not cids or binding.get("reason") is not None:
                errors.append(f"{field}:bound_without_support")
            if field in AMOUNTS:
                if (not isinstance(value, dict) or set(value) != {"min", "max"}
                        or type(value.get("min")) not in (int, float)
                        or not math.isfinite(value["min"]) or value["min"] < 0
                        or (value["max"] is not None and
                            (type(value["max"]) not in (int, float) or not math.isfinite(value["max"])
                             or value["max"] < value["min"]))):
                    errors.append(f"{field}:invalid_amount_range")
                proposals = binding.get("proposals") or {}
                if (set(proposals) != {"frozen_chain", "softmax/semantic", "softmax/semantic_pair"}
                        or {p.get("candidate_id") for p in proposals.values()} != set(cids)
                        or len(cids) != 1):
                    errors.append(f"{field}:candidate_consensus_mismatch")
                if isinstance(value, dict) and set(value) == {"min", "max"}:
                    parsed = [normalize_amount(ev.get("raw") or "") for ev in evidence]
                    if not any(p is not None and p["min"] == value["min"] and p["max"] == value["max"]
                               for p in parsed):
                        errors.append(f"{field}:amount_not_grounded_by_candidate")
            elif type(value) is not int or value < 0:
                errors.append(f"{field}:invalid_integer")
            if field == "persons.participant_count" and {e.get("kind") for e in evidence} != {"explicit", "list"}:
                errors.append(f"{field}:missing_dual_source_evidence")
        for ev in evidence:
            start, end = ev.get("start"), ev.get("end")
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source)
                    or source[start:end] != ev.get("quote")
                    or not any(v["start"] <= start < end <= v["end"] and v["type"] in {"facts", "meta"}
                               for v in inp["sentence_view"])):
                errors.append(f"{field}:evidence_not_in_allowed_source")
            if ev.get("candidate_id") not in cids:
                errors.append(f"{field}:evidence_candidate_unlisted")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "outputs", "manifest", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    manifest_sha = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    ins, outs = read_jsonl(args.inputs), read_jsonl(args.outputs)
    in_by, out_by = {r["id"]: r for r in ins}, {r["id"]: r for r in outs}
    failures = {}
    if len(in_by) != len(ins) or len(out_by) != len(outs) or set(in_by) != set(out_by):
        failures["_batch"] = ["missing_or_duplicate_record_ids"]
    statuses = Counter()
    for rid in sorted(set(in_by) & set(out_by)):
        errors = audit_record(in_by[rid], out_by[rid], manifest_sha)
        if errors:
            failures[rid] = sorted(set(errors))
        for b in out_by[rid].get("bindings") or []:
            statuses[f"{b.get('field')}:{b.get('binding_status')}:{b.get('reason') or 'value'}"] += 1
    report = {"status": "pass" if not failures else "fail", "records": len(ins),
              "manifest_sha256": manifest_sha, "counts": dict(sorted(statuses.items())),
              "failures": failures, "training_release_approved": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": report["status"], "records": len(ins),
                      "failed_records": len(failures)}, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

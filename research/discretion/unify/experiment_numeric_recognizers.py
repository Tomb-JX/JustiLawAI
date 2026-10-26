"""Offline E1 candidate-source comparison on frozen train/valid silver.

This measures evidence-local candidate coverage, not semantic correctness.  The
test split is never loaded into the development mapping. No text is exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.metadata import distributions
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import numeric_coverage, rows
from element_contract import normalization_spec
from supply_packet import build_packet


def recognizer_candidates(views: list[dict], vendor_root: Path | None) -> list[dict]:
    if vendor_root is not None and str(vendor_root.resolve()) not in sys.path:
        sys.path.insert(0, str(vendor_root.resolve()))
    from recognizers_suite import recognize_age, recognize_currency, recognize_number
    from recognizers_text import Culture

    e05 = normalization_spec()
    candidates = []
    seen = set()
    for view in views:
        quote = view["text"]
        for kind, fn in (("amount", recognize_currency), ("age", recognize_age),
                         ("number", recognize_number)):
            for hit in fn(quote, Culture.Chinese):
                a, b = view["start"] + hit.start, view["start"] + hit.end + 1
                raw = quote[hit.start:hit.end + 1]
                if not raw or raw != hit.text:
                    continue
                types = []
                if kind == "amount":
                    types.append("amount")
                elif kind == "age":
                    types.append("age")
                else:
                    # Deliberately generic unit check: no gambling-role words.
                    following = quote[hit.end + 1:hit.end + 4].lstrip("余多")
                    if following and following[0] in "名位人次场台张":
                        types.append("count")
                for typ in types:
                    key = (typ, a, b)
                    if key in seen:
                        continue
                    seen.add(key)
                    parsed = e05.normalize_amount(raw) if typ == "amount" else e05.normalize_count(raw)
                    candidates.append({"type": typ, "start": a, "end": b, "raw": raw,
                                       "engine_projection": parsed,
                                       "parse_status": "resolved" if parsed is not None else "unresolved"})
    return candidates


def field_summary(findings: list[dict]) -> dict:
    by_field = defaultdict(Counter)
    for finding in findings:
        path = finding["path"]
        by_field[path]["present"] += 1
        by_field[path]["candidate_found"] += bool(finding["candidate_found"])
        by_field[path]["value_found"] += bool(finding["value_found"])
    return {field: dict(counts) for field, counts in sorted(by_field.items())}


def run(teacher: Path, originals: Path, silver: Path, vendor_root: Path | None) -> dict:
    if vendor_root is not None and not vendor_root.is_dir():
        raise ValueError("recognizers_vendor_unavailable")
    reference = {r["id"]: r for r in rows(silver)
                 if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals)}
    findings = {name: [] for name in ("regex", "recognizers", "union")}
    stats = Counter()
    differences = []
    for item in rows(teacher):
        rid = item["id"]
        if rid not in reference:
            continue
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != item["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        baseline = build_packet(text, item, record_id=rid,
                                case_event_id=reference[rid]["metadata"].get("event_id"))
        recognized = recognizer_candidates(item["sentence_view"], vendor_root)
        for q in recognized:
            if text[q["start"]:q["end"]] != q["raw"]:
                raise ValueError("recognizer_source_mismatch")
        stats["records"] += 1
        stats["regex_candidates"] += len(baseline["quantities"])
        stats["recognizer_candidates"] += len(recognized)
        stats["recognizer_parse_unresolved"] += sum(q["parse_status"] != "resolved" for q in recognized)
        for q in baseline["quantities"]:
            stats["regex_" + q["type"]] += 1
        for q in recognized:
            stats["recognizer_" + q["type"]] += 1
            if q["parse_status"] != "resolved":
                stats["unresolved_" + q["type"]] += 1
        pairs = {
            "regex": baseline["quantities"],
            "recognizers": recognized,
            "union": baseline["quantities"] + recognized,
        }
        record_findings = {}
        for name, quantities in pairs.items():
            packet = {"quantities": quantities}
            record_findings[name] = numeric_coverage(reference[rid]["reference_elements"], packet)
            findings[name].extend(record_findings[name])
        old = {f["path"]: f for f in record_findings["regex"]}
        new = {f["path"]: f for f in record_findings["recognizers"]}
        for path in old.keys() & new.keys():
            if old[path]["value_found"] != new[path]["value_found"]:
                evidence = reference[rid]["reference_elements"][path.split(".")[0]][path.split(".")[1]]["evidence"]
                relevant = [q for q in recognized if q["type"] == ("amount" if path.startswith("amounts.")
                            else "age" if path == "person.age" else "count") and any(
                                ev["start"] <= q["start"] < q["end"] <= ev["end"] for ev in evidence)]
                differences.append({"id": rid, "field": path, "regex_value_found": old[path]["value_found"],
                                    "recognizer_value_found": new[path]["value_found"],
                                    "recognizer_raw": [q["raw"] for q in relevant],
                                    "recognizer_projection": [q["engine_projection"] for q in relevant]})
    if stats["records"] != len(reference):
        raise ValueError(f"development_record_count:{stats['records']}!={len(reference)}")
    return {
        "scope": "train_valid_only", "silver_is_not_gold": True,
        "metric": "evidence_local_candidate_and_e05_value_coverage",
        "input_sha256": {"teacher": hashlib.sha256(teacher.read_bytes()).hexdigest(),
                         "originals": hashlib.sha256(originals.read_bytes()).hexdigest(),
                         "silver": hashlib.sha256(silver.read_bytes()).hexdigest()},
        "recognizer_dependencies": ({d.metadata["Name"]: d.version for d in distributions(path=[str(vendor_root)])
                                    if d.metadata["Name"].lower() in {"recognizers-text-suite", "emoji"}}
                                   if vendor_root is not None else "installed_environment"),
        "stats": dict(stats),
        "coverage": {name: field_summary(rows_) for name, rows_ in findings.items()},
        "differences": differences,
        "note": ("Recognizer count candidates require an immediately following generic count unit; "
                 "date-to-age and list-to-count derivations are outside direct candidate coverage. "
                 "Evidence-local value coincidence does not establish semantic binding."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "out"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--vendor-root", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver, args.vendor_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"stats": result["stats"], "coverage": result["coverage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

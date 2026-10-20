"""Offline train/valid supply replay. Silver labels diagnose conflicts, never certify accuracy.

The test split is deliberately excluded. No model calls or source text are written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from supply_packet import VERSION, audit_elements, build_packet


def rows(path: Path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def replay(teacher: Path, originals: Path, silver: Path) -> tuple[dict, list[dict]]:
    origins = {r["id"]: r["text_full"] for r in rows(originals)}
    development = {r["id"]: r for r in rows(silver)
                   if r.get("metadata", {}).get("split") in {"train", "valid"}}
    counts = Counter()
    dispositions = Counter()
    failures = Counter()
    details = []
    for item in rows(teacher):
        rid = item["id"]
        if rid not in development:
            continue
        counts["development_records"] += 1
        try:
            text = origins[rid]
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != item["source_sha256"]:
                raise ValueError("source_hash_mismatch")
            packet = build_packet(text, item, record_id=rid,
                                  case_event_id=development[rid]["metadata"].get("event_id"),
                                  schema_version=development[rid].get("schema_version", "1.1.0"))
            audit = audit_elements(development[rid]["reference_elements"], packet)
            counts["packets_built"] += 1
            counts["quantity_candidates"] += len(packet["quantities"])
            counts["unresolved_candidates"] += sum(q["parse_status"] != "resolved"
                                                    for q in packet["quantities"])
            counts["subject_ambiguous"] += sum(q["actor_status"] in {"joint", "unresolved"}
                                               for q in packet["quantities"])
            dispositions.update((v["status"], v["reason"])
                                for v in audit["field_disposition"].values())
            details.append({"id": rid, "split": development[rid]["metadata"]["split"],
                            "quantity_candidates": len(packet["quantities"]),
                            "unresolved": len(packet["unresolved"]),
                            "binding_counts": audit["counts"],
                            "quarantined_fields": {k: v["reason"] for k, v in
                                                   audit["field_disposition"].items()
                                                   if v["status"] == "quarantined"}})
        except (KeyError, ValueError, TypeError) as exc:
            failures[type(exc).__name__ + ":" + str(exc)[:100]] += 1
            details.append({"id": rid, "error": str(exc)[:100]})
    counts["train_valid_expected"] = len(development)
    summary = {"version": VERSION, "scope": "train_valid_only", "silver_is_not_gold": True,
               "counts": dict(counts),
               "field_dispositions": {f"{status}:{reason}": count
                                      for (status, reason), count in sorted(dispositions.items())},
               "failures": dict(failures)}
    return summary, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--silver", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists")
    summary, details = replay(args.teacher, args.originals, args.silver)
    args.out.mkdir(parents=True)
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    with (args.out / "details.jsonl").open("w", encoding="utf-8") as dest:
        for item in details:
            dest.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

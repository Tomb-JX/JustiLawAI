"""Offline train/valid supply replay. Silver labels diagnose conflicts, never certify accuracy.

The test split is deliberately excluded. No model calls or source text are written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from supply_packet import VERSION, audit_elements, build_packet

NUMERIC_TYPES = {
    "conduct.times": "count", "conduct.duration_days": "duration",
    "amounts.personal_stake": "amount", "amounts.per_bet": "amount",
    "amounts.onsite_stake_total": "amount", "amounts.cumulative_stake": "amount",
    "amounts.commission": "amount", "amounts.illegal_gain": "amount",
    "persons.participant_count": "count", "persons.cumulative_participants": "count",
    "persons.abroad_organized_count": "count", "person.age": "age",
}


def same_value(path: str, value, candidate: dict) -> bool:
    projection = candidate.get("engine_projection") or {}
    try:
        if path.startswith("amounts."):
            return (Decimal(str(value["min"])) == Decimal(str(projection["min"])) and
                    (value.get("max") is None and projection.get("max") is None or
                     value.get("max") is not None and projection.get("max") is not None and
                     Decimal(str(value["max"])) == Decimal(str(projection["max"]))))
        if path == "conduct.duration_days":
            return Decimal(str(value)) == Decimal(str(projection["days"]))
        return type(value) is int and projection.get("exact") is True and value == projection["min"]
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False


def numeric_coverage(elements: dict, packet: dict) -> list[dict]:
    """Evidence-local candidate recall against silver; this is not semantic accuracy."""
    result = []
    for path, typ in NUMERIC_TYPES.items():
        group, field = path.split(".")
        item = elements.get(group, {}).get(field)
        if not item:
            continue
        if item.get("status") == "未提及" or item.get("value") is None:
            continue
        evidence = item.get("evidence") or []
        candidates = [q for q in packet["quantities"] if q["type"] == typ and any(
            type(ev.get("start")) is int and type(ev.get("end")) is int and
            ev["start"] <= q["start"] < q["end"] <= ev["end"] for ev in evidence)]
        result.append({"path": path, "candidate_found": bool(candidates),
                       "value_found": any(same_value(path, item["value"], q) for q in candidates),
                       "candidate_count": len(candidates),
                       "silver_status": item["status"],
                       "evidence_excerpt": " | ".join(ev.get("quote", "")[:100] for ev in evidence)[:180]})
    return result


def currency_surface_coverage(packet: dict) -> tuple[Counter, list[str]]:
    """Count visible 元 markers, including expressions the candidate regex missed."""
    counts = Counter()
    misses = []
    amounts = [q for q in packet["quantities"] if q["type"] == "amount"]
    for span in packet["visible_spans"]:
        for index, char in enumerate(span["quote"]):
            if char != "元":
                continue
            absolute = span["start"] + index
            counts["yuan_markers"] += 1
            if any(q["start"] <= absolute < q["end"] for q in amounts):
                counts["covered_by_candidate"] += 1
            else:
                counts["uncovered"] += 1
                excerpt = span["quote"][max(0, index - 18):index + 1]
                if any(mask in excerpt for mask in ("*", "x", "X")):
                    counts["uncovered_with_mask"] += 1
                misses.append(excerpt)
    return counts, misses


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
    dispositions_by_field = {}
    coverage = Counter()
    currency_coverage = Counter()
    graph_counts = Counter()
    by_field = {}
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
            currency, currency_misses = currency_surface_coverage(packet)
            currency_coverage.update(currency)
            graph_counts.update({name: len(packet[name]) for name in
                                 ("scenes", "claims", "relations", "derivations", "bindings")})
            numeric = numeric_coverage(development[rid]["reference_elements"], packet)
            for finding in numeric:
                path = finding["path"]
                if path not in by_field:
                    by_field[path] = Counter()
                for label in ("present", "candidate_found", "value_found"):
                    if label == "present" or finding[label]:
                        by_field[path][label] += 1
                        coverage[label] += 1
            counts["packets_built"] += 1
            counts["quantity_candidates"] += len(packet["quantities"])
            counts["unresolved_candidates"] += sum(q["parse_status"] != "resolved"
                                                    for q in packet["quantities"])
            counts["subject_ambiguous"] += sum(q["actor_status"] in {"joint", "unresolved"}
                                               for q in packet["quantities"])
            dispositions.update((v["status"], v["reason"])
                                for v in audit["field_disposition"].values())
            for path, disposition in audit["field_disposition"].items():
                if path not in dispositions_by_field:
                    dispositions_by_field[path] = Counter()
                dispositions_by_field[path][disposition["status"] + ":" + disposition["reason"]] += 1
            details.append({"id": rid, "split": development[rid]["metadata"]["split"],
                            "quantity_candidates": len(packet["quantities"]),
                            "unresolved": len(packet["unresolved"]),
                            "binding_counts": audit["counts"],
                            "numeric_misses": [{"path": f["path"],
                                                "reason": "value_mismatch" if f["candidate_found"]
                                                else "candidate_missing",
                                                "silver_status": f["silver_status"],
                                                "evidence_excerpt": f["evidence_excerpt"]}
                                               for f in numeric if not f["value_found"]],
                            "uncovered_currency_excerpts": currency_misses,
                            "quarantined_fields": {k: v["reason"] for k, v in
                                                   audit["field_disposition"].items()
                                                   if v["status"] == "quarantined"}})
        except (KeyError, ValueError, TypeError) as exc:
            failures[type(exc).__name__ + ":" + str(exc)[:100]] += 1
            details.append({"id": rid, "error": str(exc)[:100]})
    counts["train_valid_expected"] = len(development)
    summary = {"version": VERSION, "scope": "train_valid_only", "silver_is_not_gold": True,
               "input_sha256": {"teacher": hashlib.sha256(teacher.read_bytes()).hexdigest(),
                                "originals": hashlib.sha256(originals.read_bytes()).hexdigest(),
                                "silver": hashlib.sha256(silver.read_bytes()).hexdigest()},
               "counts": dict(counts),
               "field_dispositions": {f"{status}:{reason}": count
                                      for (status, reason), count in sorted(dispositions.items())},
               "numeric_evidence_coverage": dict(coverage),
               "numeric_evidence_coverage_by_field": {path: dict(counts)
                                                      for path, counts in sorted(by_field.items())},
               "currency_surface_coverage": dict(currency_coverage),
               "graph_item_counts": dict(graph_counts),
               "field_dispositions_by_field": {path: dict(counts)
                                               for path, counts in sorted(dispositions_by_field.items())},
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

"""E3 age operand feasibility using silver evidence and metadata date as oracles.

This is an upper-bound diagnostic. The model has not selected a birth operand,
proved person/event identity, or established the metadata date from text.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from audit_supply_replay import rows
from supply_packet import build_packet


def birth_interval(q: dict) -> tuple[date, date] | None:
    if q.get("type") != "date" or q.get("role_hint") != "birth" or q.get("parse_status") != "resolved":
        return None
    projection = q.get("engine_projection") or {}
    if "date" not in projection:
        return None
    point = date.fromisoformat(projection["date"])
    raw = q["raw"]
    if "日" in raw or "号" in raw:
        return point, point
    if "月" in raw:
        return point.replace(day=1), point.replace(day=calendar.monthrange(point.year, point.month)[1])
    if "年" in raw:
        return date(point.year, 1, 1), date(point.year, 12, 31)
    return None


def completed_age(birth: date, event: date) -> int:
    return event.year - birth.year - ((event.month, event.day) < (birth.month, birth.day))


def run(teacher: Path, originals: Path, silver: Path) -> dict:
    reference = {r["id"]: r for r in rows(silver)
                 if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals)}
    stats = Counter()
    examples = []
    for inp in rows(teacher):
        rid = inp["id"]
        if rid not in reference:
            continue
        stats["records"] += 1
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        age_item = reference[rid]["reference_elements"]["person"]["age"]
        if type(age_item.get("value")) is not int:
            continue
        stats["silver_age_positive"] += 1
        evidence = age_item.get("evidence") or []
        packet = build_packet(text, inp, record_id=rid,
                              case_event_id=reference[rid]["metadata"].get("event_id"))
        births = [q for q in packet["quantities"] if any(
            type(e.get("start")) is int and type(e.get("end")) is int and
            e["start"] <= q["start"] < q["end"] <= e["end"] for e in evidence)
            and birth_interval(q) is not None]
        if not births:
            stats["no_birth_operand_in_evidence"] += 1
            continue
        stats["birth_operand_in_evidence"] += 1
        raw_event = reference[rid]["metadata"].get("behavior_date")
        try:
            event = date.fromisoformat(raw_event)
        except (TypeError, ValueError):
            stats["no_parseable_metadata_behavior_date"] += 1
            continue
        stats["metadata_behavior_date_parseable"] += 1
        possible = set()
        ranges = []
        for q in births:
            b0, b1 = birth_interval(q)
            low, high = completed_age(b1, event), completed_age(b0, event)
            if 0 <= low <= high <= 130:
                ranges.append((low, high))
                possible.update(range(low, high + 1))
        if not ranges:
            stats["invalid_age_range"] += 1
        elif len(possible) == 1:
            stats["unique_exact_age"] += 1
            value = next(iter(possible))
            stats["exact_matches_silver" if value == age_item["value"] else "exact_disagrees_silver"] += 1
            if value != age_item["value"] and len(examples) < 12:
                examples.append({"id": rid, "derived": value, "silver": age_item["value"],
                                 "birth_raw": [q["raw"] for q in births], "event_date": raw_event})
        else:
            stats["age_interval_or_ambiguous_operands"] += 1
            if age_item["value"] in possible:
                stats["interval_contains_silver"] += 1
    if stats["records"] != len(reference):
        raise ValueError("development_record_count_mismatch")
    return {"scope": "train_valid_only", "silver_is_not_gold": True,
            "oracle_evidence_and_metadata_date": True,
            "input_sha256": {"teacher": hashlib.sha256(teacher.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver.read_bytes()).hexdigest()},
            "stats": dict(stats), "disagreements": examples,
            "note": "Only arithmetic and operand availability are measured; person/event binding remains unsolved."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result["stats"], ensure_ascii=False))


if __name__ == "__main__":
    main()

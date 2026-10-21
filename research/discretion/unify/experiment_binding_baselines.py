"""Offline E2 binding baselines on frozen train/valid, with sealed test excluded.

The evidence filter is an oracle diagnostic, never a deployable input. Silver
agreement is not accuracy, and missing silver fields are not verified negatives.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows, same_value
from supply_packet import build_packet

FIELDS = {
    "amounts.personal_stake": ("amount", "personal_stake", True),
    "amounts.onsite_stake_total": ("amount", "onsite_stake_total", False),
    "persons.participant_count": ("count", "participant_count", False),
    "person.age": ("age", "age", True),
}


def candidates_for(field: str, quantities: list[dict], *, guard_actor: bool,
                   evidence: list[dict] | None) -> list[dict]:
    typ, role, subject_specific = FIELDS[field]
    result = []
    for q in quantities:
        if q["type"] != typ or q.get("role_hint") != role or q.get("parse_status") != "resolved":
            continue
        if guard_actor and subject_specific and q.get("actor_status") != "target":
            continue
        if evidence is not None and not any(
                type(e.get("start")) is int and type(e.get("end")) is int
                and e["start"] <= q["start"] < q["end"] <= e["end"] for e in evidence):
            continue
        result.append(q)
    return result


def select_unique(quantities: list[dict]) -> tuple[str, dict | None]:
    by_value = {}
    for q in quantities:
        p = q["engine_projection"]
        key = (str(p.get("min")), str(p.get("max")), p.get("exact"))
        by_value.setdefault(key, q)
    if not by_value:
        return "no_candidate", None
    if len(by_value) > 1:
        return "ambiguous", None
    return "selected", next(iter(by_value.values()))


def run(teacher: Path, originals: Path, silver: Path) -> dict:
    reference = {r["id"]: r for r in rows(silver)
                 if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals)}
    variants = ("role_only", "role_actor", "oracle_role", "oracle_role_actor")
    totals = {v: defaultdict(Counter) for v in variants}
    examples = {v: defaultdict(list) for v in variants}
    record_count = 0
    for inp in rows(teacher):
        rid = inp["id"]
        if rid not in reference:
            continue
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        record_count += 1
        packet = build_packet(text, inp, record_id=rid,
                              case_event_id=reference[rid]["metadata"].get("event_id"))
        for field in FIELDS:
            group, name = field.split(".")
            silver_item = reference[rid]["reference_elements"][group][name]
            positive = silver_item.get("value") is not None and silver_item.get("status") != "未提及"
            for variant in variants:
                oracle = variant.startswith("oracle_")
                evidence = silver_item.get("evidence") or [] if oracle else None
                qs = candidates_for(field, packet["quantities"],
                                    guard_actor=variant.endswith("actor"), evidence=evidence)
                state, selected = select_unique(qs)
                counts = totals[variant][field]
                counts["records"] += 1
                counts["silver_positive" if positive else "silver_missing"] += 1
                counts[state] += 1
                if positive:
                    counts["positive_" + state] += 1
                    if selected is not None:
                        label = "silver_match" if same_value(field, silver_item["value"], selected) else "silver_disagree"
                        counts[label] += 1
                        if label == "silver_disagree" and len(examples[variant][field]) < 8:
                            examples[variant][field].append({"id": rid, "outcome": label,
                                                             "candidate_raw": selected["raw"],
                                                             "candidate_actor": selected["actor_status"]})
                elif selected is not None:
                    counts["silver_missing_but_selected"] += 1
    if record_count != len(reference):
        raise ValueError(f"development_record_count:{record_count}!={len(reference)}")
    return {
        "scope": "train_valid_only", "silver_is_not_gold": True,
        "oracle_is_not_deployable": True, "records": record_count,
        "input_sha256": {"teacher": hashlib.sha256(teacher.read_bytes()).hexdigest(),
                         "originals": hashlib.sha256(originals.read_bytes()).hexdigest(),
                         "silver": hashlib.sha256(silver.read_bytes()).hexdigest()},
        "variants": {v: {f: dict(c) for f, c in sorted(by_field.items())}
                     for v, by_field in totals.items()},
        "silver_disagreement_examples": {v: dict(examples[v]) for v in variants},
        "limitations": ["role_hint and actor_status are regex heuristics, not learned relations",
                        "onsite total does not prove target scene membership",
                        "silver missing fields may be false negatives",
                        "oracle variants use silver evidence spans only to isolate binding errors"],
    }


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
    print(json.dumps({"records": result["records"], "variants": result["variants"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

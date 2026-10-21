"""Pair original engine S2 with the E2 rules on identical train/valid views.

This is relative to silver field values, not gold edge or field accuracy. The
original S2 extracts its own candidates, so this is a system comparison rather
than a same-candidate relation-model ablation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows, same_value
from experiment_binding_baselines import FIELDS, candidates_for, select_unique
from supply_packet import build_packet


def projection(value) -> dict:
    if isinstance(value, dict):
        return value
    if type(value) is int:
        return {"min": value, "max": value, "exact": True}
    return {}


def run(teacher: Path, originals: Path, silver: Path, engine_root: Path) -> dict:
    binding_source = engine_root / "app/discretion/binding.py"
    if not binding_source.is_file():
        raise ValueError("engine_binding_missing")
    sys.path.insert(0, str(engine_root.resolve()))
    from app.discretion.binding import bind

    refs = {r["id"]: r for r in rows(silver)
            if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals)}
    totals = defaultdict(Counter)
    disagreements = []
    n = 0
    for inp in rows(teacher):
        rid = inp["id"]
        if rid not in refs:
            continue
        n += 1
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        meta = refs[rid]["metadata"]
        original = bind(inp["sentence_view"], inp["target"], inp.get("aliases") or (),
                        behavior_date=meta.get("behavior_date"))
        packet = build_packet(text, inp, record_id=rid, case_event_id=meta.get("event_id"))
        for field in FIELDS:
            group, name = field.split(".")
            label = refs[rid]["reference_elements"][group][name]
            positive = label.get("value") is not None and label.get("status") != "未提及"
            old = original.bindings.get(field)
            role_state, role_q = select_unique(candidates_for(
                field, packet["quantities"], guard_actor=False, evidence=None))
            actor_state, actor_q = select_unique(candidates_for(
                field, packet["quantities"], guard_actor=True, evidence=None))
            selected = {"original_s2": projection(old.value) if old else None,
                        "e2_role": role_q["engine_projection"] if role_q else None,
                        "e2_role_actor": actor_q["engine_projection"] if actor_q else None}
            status = {}
            counts = totals[field]
            counts["records"] += 1
            counts["silver_positive" if positive else "silver_missing"] += 1
            for method, value in selected.items():
                if value is None:
                    status[method] = "abstain"
                    continue
                counts[method + "_selected"] += 1
                if positive:
                    match = same_value(field, label["value"], {"engine_projection": value})
                    status[method] = "match" if match else "disagree"
                    counts[method + "_silver_" + status[method]] += 1
                else:
                    status[method] = "silver_missing"
                    counts[method + "_silver_missing_selected"] += 1
            if positive:
                counts["both_original_and_role_match"] += (status["original_s2"] == "match"
                                                           and status["e2_role"] == "match")
                counts["only_original_match"] += (status["original_s2"] == "match"
                                                  and status["e2_role"] != "match")
                counts["only_role_match"] += (status["original_s2"] != "match"
                                              and status["e2_role"] == "match")
                if status["original_s2"] != status["e2_role"]:
                    disagreements.append({"id": rid, "field": field,
                                          "original_s2": status["original_s2"],
                                          "e2_role": status["e2_role"],
                                          "e2_role_actor": status["e2_role_actor"],
                                          "e2_role_state": role_state,
                                          "e2_actor_state": actor_state,
                                          "original_candidate_id": old.candidate_id if old else None,
                                          "e2_candidate_id": role_q["candidate_id"] if role_q else None})
    if n != len(refs):
        raise ValueError("development_record_count_mismatch")
    return {"scope": "train_valid_only", "records": n, "silver_is_not_gold": True,
            "input_sha256": {"teacher": hashlib.sha256(teacher.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver.read_bytes()).hexdigest(),
                             "original_s2_binding_py": hashlib.sha256(binding_source.read_bytes()).hexdigest()},
            "counts": {field: dict(c) for field, c in sorted(totals.items())},
            "disagreements": disagreements,
            "limitations": ["Both systems receive the same allowed views and target",
                            "Original S2 uses its own candidate extractor",
                            "Behavior date comes from silver metadata, not a relation prediction",
                            "Silver missing is not a verified negative",
                            "Neither field agreement nor paired disagreement establishes gold edge quality"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "engine_root", "out"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver, args.engine_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"records": result["records"], "counts": result["counts"],
                      "disagreements": len(result["disagreements"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

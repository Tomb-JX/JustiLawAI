"""Audit whether defensible cross-field graph constraints change valid outputs.

This is an activation test, not an edge-accuracy estimate or ILP benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from experiment_age_count_closure import age_prediction, count_candidates
from experiment_participant_list import candidate_lists
from minimal_amount_closure import load_records
from validate_simple_review import validate

AMOUNTS = ("amounts.personal_stake", "amounts.onsite_stake_total")


def run(teacher: Path, originals: Path, silver: Path, suite_report: Path,
        suite_predictions: Path, review_cases: Path, review: Path) -> dict:
    report = json.loads(suite_report.read_text("utf-8"))
    if report["scope"] != "train_event_oof_valid_diagnostic" or report["test_labels_read"]:
        raise ValueError("suite_scope_mismatch")
    check = validate(review_cases, review)
    if not check["valid"] or check["counts"].get("complete") != check["cases"]:
        raise ValueError("review_invalid")
    reviewed = json.loads(review.read_text("utf-8"))["cases"]
    dual = [c["id"] for c in reviewed if all(
        c["answers"][f]["decision"] == "candidate" for f in
        ("personal_stake", "onsite_stake_total")) and
        c["answers"]["personal_stake"]["candidate_id"] ==
        c["answers"]["onsite_stake_total"]["candidate_id"]]
    records = load_records(teacher, originals, silver, {"train", "valid"})
    val = {rid: (inp, packet, ref) for rid, inp, packet, ref in records
           if ref["metadata"]["split"] == "valid"}
    pred = {(r["id"], r["field"], r["config"]): r for r in rows(suite_predictions)
            if r.get("field") in AMOUNTS}
    stats = Counter()
    violations = []
    for rid, (inp, packet, _) in val.items():
        quantities = {q["candidate_id"]: q for q in packet["quantities"]}
        for config in ("surface", "local_relation", "scene_relation"):
            choices = {}
            for field in AMOUNTS:
                row = pred[(rid, field, config)]
                threshold = report["amounts"][field][config]["threshold"]
                qid = row["candidate_id"] if row["candidate_id"] and row["score"] >= threshold else None
                choices[field] = qid
                if qid is None:
                    continue
                q = quantities.get(qid)
                stats[config + ":selected"] += 1
                if q is None or q["type"] != "amount" or q["parse_status"] != "resolved":
                    violations.append({"id": rid, "field": field, "config": config, "candidate_id": qid})
                if q and q.get("actor_status") == "other":
                    stats[config + ":heuristic_other_actor"] += 1
            safe_choices = {field: qid if qid is None or (
                qid in quantities and quantities[qid]["type"] == "amount" and
                quantities[qid]["parse_status"] == "resolved") else None
                for field, qid in choices.items()}
            stats[config + ":safe_decoder_changed_fields"] += sum(
                choices[field] != safe_choices[field] for field in AMOUNTS)
            if all(choices.values()) and len(set(choices.values())) == 1:
                stats[config + ":same_candidate_two_fields"] += 1
            stats[config + ":records"] += 1
    if violations:
        raise ValueError("safe_constraint_violation")
    for rid, inp, packet, ref in records:
        split = ref["metadata"]["split"]
        lists = candidate_lists(packet, inp["target"], inp.get("aliases") or ())
        explicit = {q["engine_projection"]["min"] for q in count_candidates(packet)
                    if q.get("role_hint") == "participant_count"}
        stats[split + ":records"] += 1
        stats[split + ":list_present"] += bool(lists)
        stats[split + ":list_explicit_value_conflict"] += bool(
            lists and explicit and any(l["value"] not in explicit for l in lists))
        age = age_prediction(packet)
        stats[split + ":age_ambiguous"] += age.get("reason") == "ambiguous_age_or_event"
    return {"scope": "valid_same_candidate_constraint_activation", "test_labels_read": False,
            "valid_records": len(val), "counts": dict(stats),
            "safe_cross_field_constraint_changes": sum(
                stats[c + ":safe_decoder_changed_fields"] for c in
                ("surface", "local_relation", "scene_relation")),
            "reason": "Only source/type/one-output-per-field are mechanically justified here; "
                      "these are already enforced by candidate construction and individual decoding.",
            "same_candidate_two_roles_in_single_reviewer_pilot": dual,
            "candidate_exclusivity_is_invalid": bool(dual),
            "review_is_not_population_gold": True,
            "input_sha256": {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in
                             {"suite_report": suite_report, "suite_predictions": suite_predictions,
                              "review": review, "review_cases": review_cases}.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "suite_report", "suite_predictions",
                 "review_cases", "review", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver, args.suite_report,
                 args.suite_predictions, args.review_cases, args.review)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

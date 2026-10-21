"""Compare one person's six-case choice review with silver and frozen valid ranker.

This produces a disagreement inventory, not accuracy or adjudicated gold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows, same_value
from validate_simple_review import validate


def weak_candidates(field: str, item: dict, amounts: list[dict]) -> list[dict]:
    if item.get("value") is None or item.get("status") == "未提及":
        return []
    return [q for q in amounts if same_value(field, item["value"], {"engine_projection": _projection(q["raw"])})
            and any(type(e.get("start")) is int and type(e.get("end")) is int
                    and e["start"] <= q["start"] < q["end"] <= e["end"]
                    for e in item.get("evidence") or [])]


def _projection(raw: str) -> dict:
    # Use the single E-05 normalizer instead of another number parser.
    from element_contract import normalization_spec
    return normalization_spec().normalize_amount(raw) or {}


def run(cases_path: Path, review_path: Path, silver_path: Path, selective_path: Path) -> dict:
    check = validate(cases_path, review_path)
    if not check["valid"] or check["counts"].get("complete") != check["cases"]:
        raise ValueError("review_incomplete_or_invalid:" + ",".join(check["issues"]))
    cases = {c["id"]: c for c in json.loads(cases_path.read_text("utf-8"))}
    review = json.loads(review_path.read_text("utf-8"))
    silver = {r["id"]: r for r in rows(silver_path) if r["id"] in cases}
    if set(silver) != set(cases):
        raise ValueError("silver_case_scope_mismatch")
    selective = json.loads(selective_path.read_text("utf-8"))
    if selective.get("scope") != "train_event_oof_threshold_valid_evaluation":
        raise ValueError("selective_result_scope_mismatch")
    predictions = {field: {r["id"]: r for r in data["valid_rows"]}
                   for field, data in selective["fields"].items()}
    totals = Counter()
    details = []
    for form in review["cases"]:
        rid = form["id"]
        case = cases[rid]
        ref = silver[rid]
        split = ref["metadata"]["split"]
        for short in ("personal_stake", "onsite_stake_total"):
            field = "amounts." + short
            answer = form["answers"][short]
            item = ref["reference_elements"]["amounts"][short]
            silver_positive = item.get("value") is not None and item.get("status") != "未提及"
            matches = weak_candidates(field, item, case["amounts"])
            human_id = answer.get("candidate_id") if answer["decision"] == "candidate" else None
            human_q = next((q for q in case["amounts"] if q["candidate_id"] == human_id), None)
            model = predictions[field].get(rid) if split == "valid" else None
            if silver_positive:
                match_ids = {q["candidate_id"] for q in matches}
                outcome = ("human_matches_unique_silver_evidence" if len(match_ids) == 1 and human_id in match_ids
                           else "human_within_ambiguous_silver_evidence" if len(match_ids) > 1 and human_id in match_ids
                           else "human_silver_disagree_or_unresolved")
            elif human_id is not None:
                outcome = "human_candidate_silver_missing"
            elif answer["decision"] == "absent":
                outcome = "human_absent_silver_missing"
            else:
                outcome = "human_uncertain_silver_missing"
            totals[short + ":" + outcome] += 1
            details.append({"id": rid, "split": split, "field": field,
                            "human_decision": answer["decision"], "human_candidate_id": human_id,
                            "human_raw": human_q["raw"] if human_q else None,
                            "human_start": human_q["start"] if human_q else None,
                            "human_relation": answer.get("relation"),
                            "silver_positive": silver_positive,
                            "silver_value": item.get("value"),
                            "silver_evidence_candidate_ids": [q["candidate_id"] for q in matches],
                            "comparison": outcome,
                            "valid_ranker_candidate_id": model["selected_id"] if model else None,
                            "human_matches_valid_ranker": human_id == model["selected_id"] if model else None})
    return {"scope": "single_reviewer_six_case_disagreement_inventory", "human_gold": False,
            "population_accuracy_allowed": False, "test_split_used": False,
            "reviewer_id_provided": bool(review.get("reviewer_id")),
            "cases": len(cases), "decisions": len(details), "counts": dict(totals), "details": details,
            "input_sha256": {"cases": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
                             "review": hashlib.sha256(review_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
                             "selective": hashlib.sha256(selective_path.read_bytes()).hexdigest()},
            "limitations": ["Single reviewer, no adjudication", "Disagreement-enriched pilot is not a random sample",
                            "Silver missing is not proven field absence", "Train cases have no frozen OOF ranker output in this report"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cases", "review", "silver", "selective", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.cases, args.review, args.silver, args.selective)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"cases": result["cases"], "counts": result["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

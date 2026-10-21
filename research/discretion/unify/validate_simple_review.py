"""Validate exported choice-based amount review against source-bound pilot cases."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

FIELDS = ("personal_stake", "onsite_stake_total")
DECISIONS = {"candidate", "absent", "unclear", "missed"}
RELATIONS = {"personal_stake": {"target", "other", "shared", "unclear"},
             "onsite_stake_total": {"target_event", "other_event", "unclear"}}


def validate(cases_path: Path, review_path: Path) -> dict:
    cases = json.loads(cases_path.read_text("utf-8"))
    payload = json.loads(review_path.read_text("utf-8"))
    issues = []
    counts = Counter()
    if payload.get("schema") != "simple-amount-edge-review-v1":
        issues.append("schema_mismatch")
    forms = payload.get("cases")
    if not isinstance(forms, list) or len(forms) != len(cases):
        return {"valid": False, "issues": issues + ["case_count_mismatch"]}
    for case, form in zip(cases, forms):
        rid = case["id"]
        if form.get("id") != rid or form.get("source_sha256") != case["source_sha256"]:
            issues.append(rid + ":source_identity_mismatch")
        status = form.get("review_status")
        if status not in {"pending", "complete"}:
            issues.append(rid + ":invalid_status")
        counts[str(status)] += 1
        answers = form.get("answers") or {}
        ids = {q["candidate_id"] for q in case["amounts"]}
        for field in FIELDS:
            answer = answers.get(field) or {}
            decision = answer.get("decision")
            if decision is None and status == "pending":
                continue
            if decision not in DECISIONS:
                issues.append(rid + ":" + field + ":invalid_decision")
                continue
            counts[field + ":" + decision] += 1
            if decision == "candidate":
                if answer.get("candidate_id") not in ids:
                    issues.append(rid + ":" + field + ":candidate_not_in_case")
                if answer.get("relation") not in RELATIONS[field]:
                    issues.append(rid + ":" + field + ":invalid_relation")
            elif answer.get("candidate_id") is not None or answer.get("relation") is not None:
                issues.append(rid + ":" + field + ":stale_candidate_or_relation")
            if decision == "missed":
                quote = (answer.get("missed_quote") or "").strip()
                if not quote or not any(quote in v["text"] for v in case["allowed_views"]):
                    issues.append(rid + ":" + field + ":missed_quote_not_in_allowed_view")
    return {"valid": not issues, "cases": len(cases), "counts": dict(counts), "issues": issues,
            "complete_single_reviewer_gold": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.cases, args.review)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

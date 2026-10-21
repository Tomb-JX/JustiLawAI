"""Validate source coordinates and completeness of independent edge review forms."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows

DECISIONS = {"asserted", "negated", "not_relevant", "uncertain"}
ROLES = {"amounts.personal_stake", "amounts.onsite_stake_total",
         "persons.participant_count", "person.age", "birth_date",
         "behavior_date", "other_numeric"}


def grounded(span: dict, views: list[dict]) -> bool:
    a, b = span.get("start"), span.get("end")
    return type(a) is int and type(b) is int and any(
        v["start"] <= a < b <= v["end"] for v in views)


def validate(cases_path: Path, review_path: Path) -> dict:
    cases = {r["id"]: r for r in rows(cases_path)}
    reviews = list(rows(review_path))
    issues = []
    counts = Counter()
    if len(reviews) != len(cases) or len({r.get("id") for r in reviews}) != len(reviews):
        issues.append("case_count_or_duplicate_id")
    for form in reviews:
        rid = form.get("id")
        if rid not in cases:
            issues.append(f"{rid}:unexpected_case")
            continue
        case = cases[rid]
        if form.get("source_sha256") != case["source_sha256"]:
            issues.append(f"{rid}:source_hash_mismatch")
        complete = form.get("review_status") == "complete"
        if form.get("review_status") not in {"pending", "complete"}:
            issues.append(f"{rid}:invalid_status")
        if complete and not form.get("reviewer_id"):
            issues.append(f"{rid}:reviewer_missing")
        expected = {q["candidate_id"] for q in case["candidates"]}
        found = Counter(edge.get("candidate_id") for edge in form.get("quantity_edges", []))
        if set(found) != expected:
            issues.append(f"{rid}:candidate_ids_missing_or_extra")
        entity_ids = {"T", *(e.get("entity_id") for e in form.get("entities", []))}
        event_ids = {e.get("event_id") for e in form.get("events", [])}
        memberships = {(m.get("actor_id"), m.get("event_id")) for m in
                       form.get("event_membership_edges", [])}
        for edge in form.get("quantity_edges", []):
            decision = edge.get("decision")
            if complete and decision not in DECISIONS:
                issues.append(f"{rid}:{edge.get('candidate_id')}:decision_missing_or_invalid")
            if decision == "asserted" and edge.get("field_role") not in ROLES:
                issues.append(f"{rid}:{edge.get('candidate_id')}:role_missing_or_invalid")
            if complete and decision == "asserted" and not edge.get("support_spans"):
                issues.append(f"{rid}:{edge.get('candidate_id')}:support_missing")
            if complete and decision == "asserted" and edge.get("polarity") not in {"positive", "negative", "uncertain"}:
                issues.append(f"{rid}:{edge.get('candidate_id')}:polarity_missing")
            if complete and decision == "asserted" and edge.get("field_role") in {"amounts.personal_stake", "person.age", "birth_date"} and not edge.get("actor_ids"):
                issues.append(f"{rid}:{edge.get('candidate_id')}:actor_missing")
            if complete and decision == "asserted" and edge.get("field_role") in {"amounts.onsite_stake_total", "persons.participant_count", "behavior_date"} and not edge.get("event_id"):
                issues.append(f"{rid}:{edge.get('candidate_id')}:event_missing")
            if complete and decision == "asserted" and edge.get("field_role") in {"amounts.onsite_stake_total", "persons.participant_count"} and ("T", edge.get("event_id")) not in memberships:
                issues.append(f"{rid}:{edge.get('candidate_id')}:target_event_membership_missing")
            if edge.get("field_role") is not None and edge["field_role"] not in ROLES:
                issues.append(f"{rid}:{edge.get('candidate_id')}:invalid_role")
            if any(eid not in entity_ids for eid in edge.get("actor_ids", [])):
                issues.append(f"{rid}:{edge.get('candidate_id')}:unknown_actor")
            if edge.get("event_id") is not None and edge["event_id"] not in event_ids:
                issues.append(f"{rid}:{edge.get('candidate_id')}:unknown_event")
            if any(not grounded(s, case["allowed_views"]) for s in edge.get("support_spans", [])):
                issues.append(f"{rid}:{edge.get('candidate_id')}:support_outside_allowed_view")
            counts["quantity_edges"] += 1
            counts["decision_" + str(decision)] += 1
        for item in form.get("missed_candidate_spans", []):
            if not grounded(item, case["allowed_views"]):
                issues.append(f"{rid}:missed_candidate_outside_allowed_view")
        for entity in form.get("entities", []):
            if complete and not entity.get("entity_id"):
                issues.append(f"{rid}:entity_id_missing")
            if complete and not entity.get("mentions"):
                issues.append(f"{rid}:entity_mentions_missing")
            if any(not grounded(s, case["allowed_views"]) for s in entity.get("mentions", [])):
                issues.append(f"{rid}:entity_mention_outside_allowed_view")
        for event in form.get("events", []):
            if complete and not event.get("event_id"):
                issues.append(f"{rid}:event_id_missing")
            if complete and not event.get("support_spans"):
                issues.append(f"{rid}:event_support_missing")
            if any(not grounded(s, case["allowed_views"]) for s in event.get("support_spans", [])):
                issues.append(f"{rid}:event_support_outside_allowed_view")
        for member in form.get("event_membership_edges", []):
            if member.get("actor_id") not in entity_ids or member.get("event_id") not in event_ids:
                issues.append(f"{rid}:membership_unknown_actor_or_event")
            if member.get("decision") not in DECISIONS:
                issues.append(f"{rid}:membership_decision_invalid")
            if complete and not member.get("support_spans"):
                issues.append(f"{rid}:membership_support_missing")
            if any(not grounded(s, case["allowed_views"]) for s in member.get("support_spans", [])):
                issues.append(f"{rid}:membership_support_outside_allowed_view")
        counts["complete" if complete else "pending"] += 1
    return {"cases": len(cases), "review_forms": len(reviews), "counts": dict(counts),
            "valid": not issues, "issues": issues}


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

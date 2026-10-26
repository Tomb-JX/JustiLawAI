"""Focused checks for experimental selectors and calendar bounds."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiment_age_derivation import birth_interval, completed_age
from experiment_binding_baselines import candidates_for, select_unique
from validate_edge_review import validate
from evaluate_edge_review import target_relation, score
from experiment_weak_role_model import CharNB, independent, joint
from experiment_pairwise_binding_ranker import train_ranker, dot
from validate_simple_review import validate as validate_simple
from experiment_silver_supervised_pipeline import SparseLogistic, measure
from collections import Counter


def test_unique_selection_deduplicates_same_value_but_abstains_on_distinct_values():
    one = {"engine_projection": {"min": 100, "max": 100}}
    two = {"engine_projection": {"min": 200, "max": 200}}
    assert select_unique([one, dict(one)])[0] == "selected"
    assert select_unique([one, two]) == ("ambiguous", None)


def test_actor_guard_exposes_missing_subject_link():
    q = {"type": "age", "role_hint": "age", "parse_status": "resolved",
         "actor_status": "unresolved", "start": 8, "end": 11}
    assert candidates_for("person.age", [q], guard_actor=False, evidence=None) == [q]
    assert candidates_for("person.age", [q], guard_actor=True, evidence=None) == []


def test_birth_interval_preserves_precision_instead_of_using_synthetic_point():
    year = {"type": "date", "role_hint": "birth", "parse_status": "resolved",
            "raw": "2000年", "engine_projection": {"date": "2000-07-01"}}
    month = {**year, "raw": "2000年2月", "engine_projection": {"date": "2000-02-01"}}
    assert birth_interval(year) == (date(2000, 1, 1), date(2000, 12, 31))
    assert birth_interval(month) == (date(2000, 2, 1), date(2000, 2, 29))
    assert completed_age(date(2000, 2, 29), date(2024, 2, 28)) == 23


def test_edge_review_validator_rejects_missing_decision_and_bad_source_span(tmp_path):
    case = {"id": "R", "source_sha256": "hash", "allowed_views": [
        {"start": 0, "end": 5, "text": "abcde"}],
        "candidates": [{"candidate_id": "Q1"}]}
    form = {"id": "R", "source_sha256": "hash", "reviewer_id": "human-1",
            "review_status": "complete", "entities": [], "events": [],
            "quantity_edges": [{"candidate_id": "Q1", "decision": None,
                                "support_spans": [{"start": 5, "end": 7}]}],
            "missed_candidate_spans": []}
    cases, reviews = tmp_path / "cases.jsonl", tmp_path / "reviews.jsonl"
    cases.write_text(json.dumps(case) + "\n", encoding="utf-8")
    reviews.write_text(json.dumps(form) + "\n", encoding="utf-8")
    result = validate(cases, reviews)
    assert not result["valid"]
    assert any("decision_missing" in issue for issue in result["issues"])
    assert any("support_outside_allowed_view" in issue for issue in result["issues"])


def test_target_relation_requires_actor_or_event_membership():
    personal = {"actor_ids": ["P1"], "event_id": "E1"}
    onsite = {"actor_ids": [], "event_id": "E1"}
    assert target_relation(personal, {"E1": "asserted"}, "amounts.personal_stake") == "no"
    assert target_relation(onsite, {"E1": "asserted"}, "amounts.onsite_stake_total") == "yes"
    assert target_relation(onsite, {}, "amounts.onsite_stake_total") == "unknown"
    assert score({("R", "Q", "f")}, {("R", "Q", "f")}, set())["f1"] == 1.0
    assert score({("R", "Q1", "f")}, {("R", "Q2", "f")}, set())["f1"] == 0.0


def test_joint_assignment_never_uses_one_candidate_for_both_roles():
    q1 = {"candidate_id": "Q1", "start": 1}
    q2 = {"candidate_id": "Q2", "start": 2}
    scored = [(q1, {"personal": 0.9, "onsite": 0.9}),
              (q2, {"personal": 0.7, "onsite": 0.8})]
    assert independent(scored, 0.5)["personal"] == q1
    assert independent(scored, 0.5)["onsite"] == q1
    chosen = joint(scored, 0.5)
    assert chosen["personal"]["candidate_id"] != chosen["onsite"]["candidate_id"]


def test_char_nb_temperature_softens_overconfident_score_without_changing_rank():
    model = CharNB()
    model.fit([(Counter({"个人": 2}), "personal"), (Counter({"现场": 2}), "onsite")])
    sharp = model.predict_proba(Counter({"个人": 3}), 1.0)
    soft = model.predict_proba(Counter({"个人": 3}), 16.0)
    assert sharp["personal"] > soft["personal"] > 0.5


def test_pairwise_ranker_learns_candidate_preference_from_positive_pair():
    positive, negative = Counter({"near_target": 1}), Counter({"far_target": 1})
    weights, stats = train_ranker([(positive, [negative])], epochs=3)
    assert stats["pairs_seen"] == 3
    assert dot(weights, positive) > dot(weights, negative)


def test_simple_review_validator_checks_candidate_and_relation(tmp_path):
    case = {"id": "R", "source_sha256": "hash", "allowed_views": [
        {"start": 0, "end": 5, "text": "100元a"}],
        "amounts": [{"candidate_id": "Q1", "raw": "100元", "start": 0, "end": 4}]}
    answer = {"decision": "candidate", "candidate_id": "Q1", "relation": "target", "missed_quote": ""}
    form = {"id": "R", "source_sha256": "hash", "review_status": "complete",
            "answers": {"personal_stake": answer,
                        "onsite_stake_total": {**answer, "relation": "target_event"}}}
    cases, review = tmp_path / "cases.json", tmp_path / "review.json"
    cases.write_text(json.dumps([case]), encoding="utf-8")
    review.write_text(json.dumps({"schema": "simple-amount-edge-review-v1", "cases": [form]}), encoding="utf-8")
    assert validate_simple(cases, review)["valid"]
    form["answers"]["personal_stake"] = {**answer, "candidate_id": "Q-other"}
    review.write_text(json.dumps({"schema": "simple-amount-edge-review-v1", "cases": [form]}), encoding="utf-8")
    assert "R:personal_stake:candidate_not_in_case" in validate_simple(cases, review)["issues"]


def test_silver_presence_model_and_field_metric_keep_wrong_value_distinct():
    model = SparseLogistic()
    model.fit([({"personal": 1.0}, True), ({"personal": 1.0}, True),
               ({"onsite": 1.0}, False), ({"onsite": 1.0}, False)])
    assert model.predict({"personal": 1.0}) > model.predict({"onsite": 1.0})
    scored = [{"id": "R1", "score": 0.9, "candidate_id": "Q1",
               "silver_positive": True, "silver_match_if_selected": False},
              {"id": "R2", "score": 0.9, "candidate_id": "Q2",
               "silver_positive": False, "silver_match_if_selected": False}]
    counts = measure(scored, 0.5)
    assert (counts["tp"], counts["fp"], counts["fn"]) == (0, 2, 1)
    assert counts["wrong_value_on_positive"] == 1
    assert counts["output_on_silver_missing"] == 1

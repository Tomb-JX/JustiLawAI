from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from review4 import _pred_key, age_alternative, age_range, key_of, problems_of  # noqa: E402

TASK = {"amount_candidates": [{"candidate_id": "Q1", "raw": "500元", "normalized": {"min": 500.0, "max": 500.0}}],
        "visible_text": [{"zone": "facts", "text": "张三，1990年5月3日出生。2022年9月27日，张三携带赌资500元\r\n参与赌博。"}]}


def test_age_is_computed_from_operands_with_precision():
    assert age_range("1990-05-03", "2022-09-27") == (32, 32)
    assert age_range("1990-05-03", "2020-05-02") == (29, 29)
    assert age_range("1990", "2022-09-27") == (31, 32)  # year-only birth spans the birthday
    assert age_range("1990-05", "2022-09-01/2022-09-30") == (32, 32)
    assert age_range(None, "2022-09-27") is None


def test_age_key_prefers_computed_and_reports_stated_conflict():
    ans = {"status": "value", "birth_date": "1990-05-03", "behavior_date": "2022-09-27", "stated_age": 33}
    assert key_of("age", ans, TASK) == "age:32"
    assert age_alternative(ans) == "age:33"
    only_stated = {"status": "value", "birth_date": None, "behavior_date": None, "stated_age": 40}
    assert key_of("age", only_stated, TASK) == "age:40"
    ambiguous = {"status": "value", "birth_date": "1990", "behavior_date": "2022-09-27", "stated_age": None}
    assert key_of("age", ambiguous, TASK) == "uncertain"


def test_amount_and_count_keys_and_service_mapping():
    assert key_of("personal_stake", {"status": "selected", "candidate_id": "Q1"}, TASK) == "amount:500"
    assert key_of("onsite_stake_total", {"status": "missing_candidate", "raw": "1 000元"}, TASK) == "amount:1000"
    assert key_of("onsite_stake_total", {"status": "missing_candidate", "raw": "一元硬币若干"}, TASK).startswith("missing:")
    assert key_of("participant_count", {"status": "value", "value": 4}, TASK) == "count:4"
    assert _pred_key("personal_stake", {"binding_status": "bound", "value": "amount:500"}) == "amount:500"
    assert _pred_key("participant_count", {"binding_status": "bound", "value": 4}) == "count:4"
    assert _pred_key("age", {"binding_status": "unresolved", "value": None}) is None
    assert _pred_key("age", {"binding_status": "absent", "value": None}) == "absent"


def test_validator_requires_verbatim_evidence_and_valid_ids():
    good = {"personal_stake": {"status": "selected", "candidate_id": "Q1", "raw": None, "evidence": "张三携带赌资500元参与赌博"},
            "onsite_stake_total": {"status": "absent", "candidate_id": None, "raw": None, "evidence": None},
            "participant_count": {"status": "uncertain", "value": None, "evidence": "参与赌博"},
            "age": {"status": "value", "birth_date": "1990-05-03", "behavior_date": "2022-09-27",
                    "stated_age": None, "evidence": "1990年5月3日出生"}, "notes": ""}
    assert problems_of(good, TASK) == []
    bad = {**good, "personal_stake": {"status": "selected", "candidate_id": "Q9", "evidence": "张三拿了五百块"},
           "age": {**good["age"], "birth_date": "1990/5/3"}}
    probs = problems_of(bad, TASK)
    assert "personal_stake:candidate_id" in probs and "personal_stake:evidence_not_verbatim" in probs
    assert "age:birth_date_format" in probs


def test_behavior_date_alone_is_absent_age():
    assert key_of("age", {"status": "value", "birth_date": None, "behavior_date": "2022-09-27",
                          "stated_age": None}, TASK) == "absent"
    assert key_of("age", {"status": "value", "birth_date": "1990-05-03", "behavior_date": None,
                          "stated_age": None}, TASK) == "uncertain"


def test_structured_amount_prediction_and_wilson():
    from review4 import wilson_low
    assert _pred_key("personal_stake", {"binding_status": "bound", "value": {"min": 500.0, "max": 500.0}}) == "amount:500"
    assert round(wilson_low(19, 20), 3) == 0.764
    assert round(wilson_low(20, 20), 3) == 0.839

from datetime import date

import pytest
from pydantic import ValidationError

from app.discretion import norm_layer as nl
from app.discretion.schema import (KEY_FIELDS, AmountRange, Evidence, Extracted, FieldStatus, GamblingElements,
                                   get_field, guideline_markdown, iter_fields, json_schema)


def test_absent_field_must_be_empty():
    with pytest.raises(ValidationError):
        Extracted[int](value=3, status=FieldStatus.ABSENT)


def test_value_requires_evidence():
    with pytest.raises(ValidationError):
        Extracted[int](value=3, status=FieldStatus.EXPLICIT)
    ok = Extracted[int](value=3, status=FieldStatus.EXPLICIT, evidence=[Evidence(quote="三人")])
    assert ok.value == 3


def test_amount_range_ordered():
    with pytest.raises(ValidationError):
        AmountRange(min=500, max=100)


def test_amount_range_open_upper():
    a = AmountRange(min=10000)
    assert a.max is None and a.open_upper and a.upper == float("inf")
    assert AmountRange(min=10000, max=10000).upper == 10000


def test_key_fields_exist_and_all_fields_documented():
    paths = {p for p, _, _ in iter_fields()}
    assert set(KEY_FIELDS) <= paths
    assert all(desc for _, desc, _ in iter_fields())
    assert "| `amounts.commission` |" in guideline_markdown()


def test_json_schema_for_constrained_decoding():
    s = json_schema()
    assert "properties" in s and "amounts" in s["properties"]


def test_elements_to_facts():
    e = GamblingElements.model_validate({
        "meta": {"behavior_date": "2026-03-12", "region": "330100"},
        "conduct": {"behavior_type": {"value": "为赌博提供条件", "status": "明确",
                                      "evidence": [{"quote": "提供包间"}]}},
        "amounts": {"commission": {"value": {"min": 800, "max": 800}, "status": "明确",
                                   "evidence": [{"quote": "收取台费约800元"}]}},
        "circumstances": {"last_prior_penalty_date": {"value": "2025-08-01", "status": "推断",
                                                      "evidence": [{"quote": "2025年8月曾因赌博被处以行政拘留"}]}},
    })
    assert get_field(e, "amounts.commission").value.min == 800
    f = nl.Facts.from_elements(e)
    assert f.behavior_type == "为赌博提供条件"
    assert f.last_prior_penalty_date == date(2025, 8, 1)
    assert f.commission.max == 800
    assert any(d.effect == "从重" for d in nl.assess(f).directions)

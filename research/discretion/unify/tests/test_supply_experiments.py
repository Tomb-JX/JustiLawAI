"""Focused checks for experimental selectors and calendar bounds."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiment_age_derivation import birth_interval, completed_age
from experiment_binding_baselines import candidates_for, select_unique


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

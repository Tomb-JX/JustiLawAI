"""Tests for binding_rules.py — field binding semantic definitions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binding_rules import FIELD_BINDING, BindingType  # noqa: E402


def test_shared_fields():
    """Scene-level fields should be SHARED."""
    shared = [f for f, t in FIELD_BINDING.items() if t == BindingType.SHARED]
    assert "amounts.onsite_stake_total" in shared
    assert "persons.participant_count" in shared
    assert "venue.venue_type" in shared
    assert "conduct.method" in shared
    assert "persons.minors_involved" in shared
    assert "persons.relatives_only" in shared


def test_target_fields():
    """Personal-level fields should be TARGET."""
    target = [f for f, t in FIELD_BINDING.items() if t == BindingType.TARGET]
    assert "conduct.behavior_type" in target
    assert "conduct.role" in target
    assert "amounts.personal_stake" in target
    assert "person.age" in target
    assert "intent.profit_purpose" in target
    assert "persons.civil_servant" in target
    assert "persons.abroad_organized_count" in target


def test_all_schema_fields_covered():
    """Every field in schema should have a binding definition."""
    from app.discretion.schema import iter_fields
    schema_paths = {p for p, _, _ in iter_fields()}
    binding_paths = set(FIELD_BINDING.keys())
    missing = schema_paths - binding_paths
    extra = binding_paths - schema_paths
    assert not missing, f"Schema fields missing from FIELD_BINDING: {missing}"
    assert not extra, f"FIELD_BINDING has fields not in schema: {extra}"


def test_shared_count_reasonable():
    """Shared fields should be a minority (scene-level is less common than personal)."""
    shared = sum(1 for t in FIELD_BINDING.values() if t == BindingType.SHARED)
    total = len(FIELD_BINDING)
    assert shared < total / 2, f"Too many shared fields: {shared}/{total}"
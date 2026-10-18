"""Tests for binding_rules.py — subject/event binding classification."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binding_rules import (BindingType, BindingResult,  # noqa: E402
                            classify_binding, classify_record_bindings,
                            binding_summary, FIELD_DEFAULT_BINDING)


# --- 字段级默认绑定 ---

def test_shared_field_defaults():
    """Scene-level fields should default to shared_fact."""
    r = classify_binding("amounts.onsite_stake_total", "现场查获赌资 3910 元",
                         target_mention="甲")
    assert r.binding_type == BindingType.SHARED

    r2 = classify_binding("persons.participant_count", "甲、乙、丙等五人赌博",
                          target_mention="甲")
    assert r2.binding_type == BindingType.SHARED

    r3 = classify_binding("venue.venue_type", "在棋牌室内", target_mention="甲")
    assert r3.binding_type == BindingType.SHARED


def test_target_field_defaults():
    """Personal-level fields should default to target_specific."""
    r = classify_binding("amounts.personal_stake", "甲持有赌资 350 元",
                         target_mention="甲")
    assert r.binding_type == BindingType.TARGET

    r2 = classify_binding("conduct.role", "甲系参赌者", target_mention="甲")
    assert r2.binding_type == BindingType.TARGET

    r3 = classify_binding("person.age", "甲，1990年出生", target_mention="甲")
    assert r3.binding_type == BindingType.TARGET


def test_target_field_with_others_mentioned():
    """Target field but evidence mentions others → needs_review."""
    r = classify_binding("amounts.personal_stake",
                         "甲和乙各持有赌资 350 元",
                         target_mention="甲", all_subjects=("甲", "乙"))
    assert r.binding_type == BindingType.REVIEW


# --- 内容依赖字段 ---

def test_behavior_type_target_specific():
    """Single-subject behavior → target_specific."""
    r = classify_binding("conduct.behavior_type",
                         "甲参与赌博",
                         target_mention="甲", all_subjects=("甲", "乙"))
    assert r.binding_type == BindingType.TARGET


def test_behavior_type_shared():
    """Multi-subject behavior → shared_fact."""
    r = classify_binding("conduct.behavior_type",
                         "甲、乙等人以打麻将方式赌博",
                         target_mention="甲", all_subjects=("甲", "乙", "丙"))
    assert r.binding_type == BindingType.SHARED


def test_times_target_only():
    """Times mentioning only target → target_specific."""
    r = classify_binding("conduct.times",
                         "甲赌博三次",
                         target_mention="甲", all_subjects=("甲", "乙"))
    assert r.binding_type == BindingType.TARGET


def test_times_shared():
    """Times mentioning multiple subjects → shared."""
    r = classify_binding("conduct.times",
                         "甲、乙等人多次赌博",
                         target_mention="甲", all_subjects=("甲", "乙"))
    assert r.binding_type == BindingType.SHARED


# --- 记录级绑定 ---

def test_classify_record_bindings():
    """Full record binding classification."""
    record = {
        "elements": {
            "amounts": {
                "onsite_stake_total": {"status": "明确", "value": {"min": 3910, "max": 3910},
                                        "evidence": [{"quote": "现场查获赌资 3910 元"}]},
                "personal_stake": {"status": "明确", "value": {"min": 350, "max": 350},
                                    "evidence": [{"quote": "甲持有赌资 350 元"}]},
            },
            "conduct": {
                "behavior_type": {"status": "明确", "value": "参与赌博",
                                   "evidence": [{"quote": "甲参与赌博"}]},
                "role": {"status": "未提及", "value": None, "evidence": []},
            },
            "persons": {
                "participant_count": {"status": "明确", "value": 5,
                                       "evidence": [{"quote": "甲、乙等五人赌博"}]},
            },
            "venue": {"venue_type": {"status": "未提及", "value": None, "evidence": []}},
            "intent": {"profit_purpose": {"status": "未提及", "value": None, "evidence": []}},
            "circumstances": {},
            "person": {"age": {"status": "未提及", "value": None, "evidence": []}},
        }
    }
    results = classify_record_bindings(record, target_mention="甲",
                                        all_subjects=("甲", "乙", "丙"))
    assert len(results) == 4  # 4 fields with values
    types = {r.field: r.binding_type for r in results}
    assert types["amounts.onsite_stake_total"] == BindingType.SHARED
    assert types["amounts.personal_stake"] == BindingType.TARGET
    assert types["conduct.behavior_type"] == BindingType.TARGET
    assert types["persons.participant_count"] == BindingType.SHARED


def test_binding_summary():
    """Summary should count by type."""
    bindings = [
        BindingResult("a", BindingType.SHARED, "ok"),
        BindingResult("b", BindingType.TARGET, "ok"),
        BindingResult("c", BindingType.REVIEW, "ambiguous"),
        BindingResult("d", BindingType.SHARED, "ok"),
    ]
    s = binding_summary(bindings)
    assert s["total"] == 4
    assert s["shared_fact"] == 2
    assert s["target_specific"] == 1
    assert s["needs_review"] == 1


# --- 覆盖所有默认绑定字段 ---

def test_all_default_fields_covered():
    """Every field in FIELD_DEFAULT_BINDING should be a valid field path."""
    from app.discretion.schema import iter_fields
    valid_paths = {p for p, _, _ in iter_fields()}
    for path in FIELD_DEFAULT_BINDING:
        assert path in valid_paths, f"{path} not in schema"
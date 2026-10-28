import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from person_mentions_ner import name_matcher, segment_people


def span(text: str, s: str) -> tuple[int, int]:
    i = text.index(s)
    return (i, i + len(s))


def test_both_models_agree():
    t = "现场扣押贺春香赌资50元"
    assert segment_people(t, [span(t, "贺春香")], [span(t, "贺春香")]) == [(*span(t, "贺春香"), "both")]


def test_single_model_needs_masked_shape_or_enumeration():
    t = "杨××、程兵、方式赌博"
    got = segment_people(t, [span(t, "杨××"), span(t, "程兵"), span(t, "方式")], [])
    kinds = {t[a:b]: k for a, b, k in got}
    assert kinds["杨××"] == "hanlp+masked"
    assert kinds["程兵"] == "hanlp+enum"   # next to 杨×× across "、"
    assert "方式" not in kinds


def test_bare_masked_name_missed_by_both_models():
    t = "现场查获匡**赌资100元"
    assert segment_people(t, [], []) == [(*span(t, "匡**"), "masked_only")]
    assert segment_people("金额***", [], []) == []


def test_target_matcher_compares_mask_runs_by_shape():
    m = name_matcher("钱**", ["钱x"])
    assert m.fullmatch("钱xx") and m.fullmatch("钱某某") and m.fullmatch("钱×")
    assert not m.fullmatch("钱建国")
    assert name_matcher("张萍波", []).fullmatch("张萍波")

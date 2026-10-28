from datetime import date

from app.discretion.decide import band_types, decide
from app.discretion.norm_layer import Facts
from app.discretion.schema import AmountRange

HEBEI, JIANGSU = "130102", "320582"


def _facts(region, **kw):
    return Facts(behavior_date=date(2023, 5, 1), decision_date=date(2023, 5, 10), region=region,
                 behavior_type="参与赌博", **kw)


def test_rule_single_uses_rule_and_legal_fine_distribution():
    d = decide(_facts(HEBEI, personal_stake=AmountRange(min=300, max=300)))
    assert (d.penalty_type, d.route, d.candidates) == ("罚款", "rule_single", ["罚款"])
    values = d.quantities["fine"]
    assert values and all(1 <= v <= 500 for v, _ in values)
    assert abs(sum(s for _, s in values) - 1) < 0.01


def test_detention_distribution_drops_values_outside_statutory_range():
    d = decide(_facts(HEBEI, personal_stake=AmountRange(min=700, max=700)))
    assert d.penalty_type == "拘留"
    assert all(1 <= v <= 5 for v, _ in d.quantities["detention_days"])   # 历史分布里的 10 日被法定幅度滤掉


def test_combined_band_gives_days_and_fine():
    d = decide(_facts(HEBEI, personal_stake=AmountRange(min=1500, max=1500)))
    assert d.penalty_type == "拘留并处罚款"
    assert all(10 <= v <= 15 for v, _ in d.quantities["detention_days"])
    assert all(500 <= v <= 3000 for v, _ in d.quantities["fine"])


def test_candidates_resolved_by_text_probabilities_only_within_candidates():
    f = _facts(JIANGSU, method="麻将", personal_stake=AmountRange(min=600, max=600))  # 方式类别不明 → 两类门槛取并集
    d = decide(f, {"拘留并处罚款": 0.6, "拘留": 0.3, "罚款": 0.1})
    assert len(d.candidates) > 1 and "拘留并处罚款" not in d.candidates
    assert d.route == "rule_candidates" and d.penalty_type == "拘留"
    assert decide(f).route == "undetermined"


def test_no_provincial_band_falls_back_to_model_or_stays_undetermined():
    f = _facts(HEBEI, method="麻将")
    d = decide(f, {"罚款": 0.7, "拘留": 0.3})
    assert (d.route, d.penalty_type, d.candidates) == ("model_fallback", "罚款", [])
    u = decide(f)
    assert (u.route, u.penalty_type, u.quantities) == ("undetermined", None, {})
    assert "一般" in u.assessment.tiers                     # 法定空间仍然给出


def test_online_without_stake_keeps_not_punishable_candidate():
    d = decide(_facts(HEBEI, method="网络赌博"), {"拘留": 0.5, "拘留并处罚款": 0.3, "不予处罚": 0.2})
    # Q-10：赌资不明时升档不足以定档，四种种类都保留为候选，候选内按文本概率选
    assert d.candidates == ["不予处罚", "拘留", "拘留并处罚款", "罚款"]
    assert d.penalty_type == "拘留" and d.quantities


def test_band_types_maps_penalty_text():
    stake = {"bands": ["未达起罚标准", "第一档", "第二档"], "band_penalty": ["处500元以下罚款", "处5日以下拘留"]}
    assert band_types(stake) == ["不予处罚", "拘留", "罚款"]
    assert band_types({"bands": [], "band_penalty": []}) == []

"""规范层测试：黄金用例（门禁 G0.2）+ 规范库自检 + 工具函数。"""
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.discretion import norm_layer as nl
from app.discretion.norm_store import load, validate
from app.discretion.schema import AmountRange

GOLDEN = yaml.safe_load((Path(__file__).parent / "golden_cases.yaml").read_text("utf-8"))
AMOUNT_FIELDS = {"personal_stake", "onsite_stake_total", "commission", "cumulative_stake"}


def to_facts(raw: dict) -> nl.Facts:
    kw = {k: AmountRange(**v) if k in AMOUNT_FIELDS else v for k, v in raw.items()}
    return nl.Facts(**kw)


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["id"] for c in GOLDEN["cases"]])
def test_golden(case):
    exp = case["expect"]
    a = nl.assess(to_facts(case["facts"]))
    assert a.law_id == exp["law"]
    effects = {d.effect for d in a.directions}
    for tier, det, fine in exp.get("allows", []):
        assert a.contains(tier, det, fine), f"应允许 {tier} 拘留{det}日 罚款{fine}元"
    for tier, det, fine in exp.get("forbids", []):
        assert not a.contains(tier, det, fine), f"不应允许 {tier} 拘留{det}日 罚款{fine}元"
    assert set(exp.get("effects", [])) <= effects
    assert not set(exp.get("no_effects", [])) & effects
    for tier, val in (exp.get("executable") or {}).items():
        assert a.tiers[tier].detention_executable is val, f"{tier} 是否执行拘留"
    for text in exp.get("review", []):
        assert any(text in n for n in a.needs_review), f"缺少复核提示：{text}；实际：{a.needs_review}"
    if "temporal" in exp:
        assert exp["temporal"] in a.temporal_note
    for want in exp.get("referral", []):
        assert any(r["item"] == want["item"] and r["status"] == want["status"] for r in a.referral), a.referral
    if "stake" in exp:
        assert a.stake_threshold["status"] == exp["stake"]


def test_golden_case_count_meets_gate():
    assert len(GOLDEN["cases"]) >= 30  # 门禁 G0.2


def test_library_self_check():
    assert validate(load()) == []


def test_cite_returns_verbatim_text():
    lib = load()
    assert lib.cite("psal-2025", "82").startswith("以营利为目的，为赌博提供条件的")
    assert "五百元以下罚款" in lib.cite("psal-2012", "70")
    assert lib.cite("apl-2021", "37").startswith("实施行政处罚，适用违法行为发生时的法律")
    assert "抽头渔利数额累计达到5000元以上" in lib.cite("spc-spp-2005-gambling", "1")
    assert "不属于“初次违反治安管理”" in lib.cite("gtz-2007-1", "5")   # 法宝原文补全的例外情形
    assert lib.cite("gtz-2005-30", "1") is None   # 未取得原文，不得引用


def test_basis_not_verified_until_signed():
    a = nl.assess(nl.Facts(behavior_date=date(2026, 3, 1), behavior_type="参与赌博"))
    assert a.basis_verified is False


def test_missing_behavior_date_rejected():
    with pytest.raises(ValueError):
        nl.assess(nl.Facts(behavior_type="参与赌博"))


def test_decision_before_behavior_rejected():
    with pytest.raises(ValueError, match="早于违法行为日期"):
        nl.assess(nl.Facts(behavior_date=date(2025, 6, 2), decision_date=date(2025, 6, 1),
                           behavior_type="参与赌博"))


def test_merge_detention_cap():
    lib = load()
    assert nl.merge_detention([15, 10], lib.law("psal-2025")) == 20
    assert nl.merge_detention([5, 5], lib.law("psal-2025")) == 10


def test_per_capita_stake():
    r = nl.per_capita_stake(AmountRange(min=4600, max=4600), 4)
    assert (r.min, r.max) == (1150, 1150)
    r = nl.per_capita_stake(AmountRange(min=5000, max=None), 5)
    assert (r.min, r.max) == (1000, None)


def _prov(region, **kw):
    base = {"behavior_date": date(2025, 6, 1), "behavior_type": "参与赌博", "region": region}
    base.update({k: AmountRange(**v) if k in AMOUNT_FIELDS else v for k, v in kw.items()})
    return nl.assess(nl.Facts(**base)).stake_threshold


@pytest.mark.parametrize("kw, status, bands", [
    # 江苏（苏公规〔2019〕1号第三节）：网络赌博属第一类，100 元起罚款档
    ({"method": "网络赌博", "personal_stake": {"min": 300, "max": 300}}, "达到赌资较大", ["第一档"]),
    ({"method": "网络赌博", "personal_stake": {"min": 1000, "max": 1000}}, "达到赌资较大", ["第三档"]),
    # 家中麻将 300 元：若属聚众赌博为第一档，否则未达 500 元起罚标准 → 三值"可能达到"
    ({"method": "麻将", "personal_stake": {"min": 300, "max": 300}}, "可能达到", ["未达起罚标准", "第一档"]),
    ({"method": "麻将", "personal_stake": {"min": 50, "max": 50}}, "已知赌资未达、其他条件待核", ["未达起罚标准"]),
    # 个人赌资查不清：现场 2000 元 ÷ 4 人 = 人均 500 元
    ({"method": "赌博机", "onsite_stake_total": {"min": 2000, "max": 2000}, "participant_count": 4},
     "达到赌资较大", ["第二档"]),
    # 国家工作人员直接升到第三档
    ({"method": "网络赌博", "personal_stake": {"min": 200, "max": 200}, "civil_servant": True}, "达到赌资较大", ["第三档"]),
])
def test_jiangsu_bands(kw, status, bands):
    r = _prov("320582", **kw)
    assert r["status"] == status and r["bands"] == bands and r["basis"] == "苏公规〔2019〕1号"


def test_jiangsu_below_min_cites_exemption():
    r = _prov("320582", method="麻将", personal_stake={"min": 50, "max": 50})
    assert any("免予处罚" in n for n in r["notes"])


@pytest.mark.parametrize("kw, bands", [
    ({"personal_stake": {"min": 300, "max": 300}}, ["情节较轻"]),
    # 个人赌资查明时只按个人定档（combine: personal_first）：个人 300（较轻），一场 1500 不再抬档
    ({"personal_stake": {"min": 300, "max": 300}, "onsite_stake_total": {"min": 1500, "max": 1500}}, ["情节较轻"]),
    # 本人 400、整场 11000：按个人定为较轻，不因他人赌资升至较重
    ({"personal_stake": {"min": 400, "max": 400}, "onsite_stake_total": {"min": 11000, "max": 11000}}, ["情节较轻"]),
    # 一场赌资达到 500 元起罚线、个人 100 未达第一档 → 托底第一档
    ({"personal_stake": {"min": 100, "max": 100}, "onsite_stake_total": {"min": 600, "max": 600}}, ["情节较轻"]),
    # 个人不明 → 按一场赌资门槛（河北专设，不用人均）
    ({"onsite_stake_total": {"min": 1226, "max": 1226}, "participant_count": 4}, ["一般情节"]),
    ({"personal_stake": {"min": 100, "max": 100}}, ["未达起罚标准"]),
    ({"personal_stake": {"min": 100, "max": 100}, "venue_type": "公共场所"}, ["情节较重"]),
    ({"personal_stake": {"min": 300, "max": None}}, ["情节较轻", "一般情节", "情节较重"]),   # "300 元以上"开口
])
def test_hebei_bands(kw, bands):
    r = _prov("130102", **kw)
    assert r["bands"] == bands


def test_provincial_note_when_new_law_applies():
    a = nl.assess(nl.Facts(behavior_date=date(2026, 3, 1), behavior_type="参与赌博", region="320582",
                           method="网络赌博", personal_stake=AmountRange(min=300, max=300)))
    assert a.law_id == "psal-2025"
    assert a.stake_threshold["status"] == "法律衔接待核验"
    assert a.stake_threshold["bands"] == []
    assert a.stake_threshold["hard_filter_allowed"] is False
    assert any("数额衔接待核验" in n for n in a.stake_threshold["notes"])
    assert any("衔接未核验" in n for n in a.needs_review)


def test_jiangsu_provide_conditions_bands():
    r = nl.assess(nl.Facts(behavior_date=date(2025, 6, 1), behavior_type="为赌博提供条件", region="320582",
                           commission=AmountRange(min=300, max=300), times=3)).stake_threshold
    assert r["status"] == "已知要素档次确定" and r["bands"] == ["第三档"]   # 获利 300（第二档）与 3 次（第三档）取较高


@pytest.mark.parametrize("region, behavior_date", [
    ("320582", date(2018, 6, 1)),  # 苏公规〔2019〕1号尚未生效
    ("130102", date(2020, 6, 1)),  # 河北 2021 修订版尚未生效
])
def test_provincial_rule_before_effective_date_abstains(region, behavior_date):
    a = nl.assess(nl.Facts(behavior_date=behavior_date, decision_date=behavior_date,
                           behavior_type="参与赌博", region=region,
                           personal_stake=AmountRange(min=600, max=600)))
    r = a.stake_threshold
    assert r["status"] == "基准未生效" and r["applicability"] == "unavailable"
    assert r["bands"] == r["band_penalty"] == []
    assert r["hard_filter_allowed"] is False
    assert a.tiers  # 国家法定空间仍可单独计算


def test_provincial_boundary_date_applies_but_never_hard_filters():
    r = nl.assess(nl.Facts(behavior_date=date(2019, 2, 2), decision_date=date(2019, 2, 3),
                           behavior_type="参与赌博", region="320582", method="网络赌博",
                           personal_stake=AmountRange(min=300, max=300))).stake_threshold
    assert r["applicability"] == "applicable" and r["bands"] == ["第一档"]
    assert r["final_band_determinable"] is False and r["hard_filter_allowed"] is False


def test_unknown_aggravator_is_not_treated_as_negative():
    base = dict(behavior_date=date(2025, 6, 1), decision_date=date(2025, 6, 2),
                behavior_type="参与赌博", region="320582", method="网络赌博",
                personal_stake=AmountRange(min=300, max=300))
    unknown = nl.assess(nl.Facts(**base)).stake_threshold
    false = nl.assess(nl.Facts(**base, civil_servant=False)).stake_threshold
    true = nl.assess(nl.Facts(**base, civil_servant=True)).stake_threshold
    assert unknown["bands"] == false["bands"] == ["第一档"]  # 已知金额投影相同
    assert "civil_servant" in unknown["unknown_conditions"]
    assert "civil_servant" not in false["unknown_conditions"]
    assert true["bands"] == ["第三档"]
    assert all(r["hard_filter_allowed"] is False for r in (unknown, false, true))


def test_elevation_without_stake_does_not_claim_stake_threshold_reached():
    r = nl.assess(nl.Facts(behavior_date=date(2025, 6, 1), decision_date=date(2025, 6, 2),
                           behavior_type="参与赌博", region="320582", civil_servant=True)).stake_threshold
    # 第七十条以"赌资较大"为前提：赌资不明时升档结果不确定，未达则不予处罚
    assert r["bands"] == ["未达起罚标准", "第三档"]
    assert r["status"] == "明确情节升档、赌资门槛未知"
    assert any("未达则不予处罚" in n for n in r["notes"])
    assert "personal_or_per_capita" in r["unknown_conditions"]


def test_elevation_with_low_stake_does_not_claim_amount_threshold_reached():
    r = nl.assess(nl.Facts(behavior_date=date(2025, 6, 1), decision_date=date(2025, 6, 2),
                           behavior_type="参与赌博", region="320582", method="麻将",
                           personal_stake=AmountRange(min=50, max=50), civil_servant=True)).stake_threshold
    assert r["bands"] == ["第三档"]
    assert r["status"] == "情节升档、已知赌资未达数额门槛"


def test_missing_decision_date_marks_provisional_temporal_scope():
    r = nl.assess(nl.Facts(behavior_date=date(2025, 6, 1), behavior_type="参与赌博",
                           region="320582", method="网络赌博",
                           personal_stake=AmountRange(min=300, max=300))).stake_threshold
    assert r["applicability"] == "provisional"
    assert any("未提供决定日期" in note for note in r["notes"])


def test_personal_known_makes_onsite_irrelevant_but_band_stays_advisory():
    r = nl.assess(nl.Facts(behavior_date=date(2025, 6, 1), region="130102",
                           behavior_type="参与赌博", personal_stake=AmountRange(min=300, max=300))).stake_threshold
    assert r["bands"] == ["情节较轻"]
    assert "onsite_stake_total" not in r["unknown_conditions"]
    assert any("按个人赌资定档" in n for n in r["notes"])
    assert r["final_band_determinable"] is False


def test_hebei_online_without_stake_keeps_not_punishable_candidate():
    r = nl.assess(nl.Facts(behavior_date=date(2023, 4, 26), decision_date=date(2023, 5, 1), region="130102",
                           behavior_type="参与赌博", method="网络赌博")).stake_threshold
    assert r["bands"] == ["未达起罚标准", "情节较重"]


def test_provide_conditions_elevation_needs_no_stake_threshold():
    # 为赌博提供条件以营利为前提，不以赌资较大为前提：升档条件照常确定档次
    r = nl.assess(nl.Facts(behavior_date=date(2023, 4, 26), decision_date=date(2023, 5, 1), region="130102",
                           behavior_type="为赌博提供条件", civil_servant=True)).stake_threshold
    assert r["bands"] == ["情节较重"]


def test_category_union_is_exact_not_interval_envelope():
    # 1200 元：江苏特殊方式第三档、其他方式第一档；第二档不在这两条分支中。
    r = nl.assess(nl.Facts(behavior_date=date(2025, 6, 1), region="320582",
                           behavior_type="参与赌博", method="麻将",
                           personal_stake=AmountRange(min=1200, max=1200))).stake_threshold
    assert r["observed_band_indices"] == [1, 3]
    assert r["bands"] == ["第一档", "第三档"]
    assert "赌博方式的省级法定类别" in r["unknown_conditions"]


def test_provincial_output_contract_never_claims_final_decision():
    cases = [
        nl.Facts(behavior_date=date(2018, 1, 1), decision_date=date(2018, 1, 2),
                 behavior_type="参与赌博", region="320582", personal_stake=AmountRange(min=300, max=300)),
        nl.Facts(behavior_date=date(2025, 6, 1), decision_date=date(2025, 6, 2),
                 behavior_type="参与赌博", region="320582", method="麻将",
                 personal_stake=AmountRange(min=1200, max=1200)),
        nl.Facts(behavior_date=date(2026, 6, 1), decision_date=date(2026, 6, 2),
                 behavior_type="参与赌博", region="320582", method="网络赌博",
                 personal_stake=AmountRange(min=300, max=300)),
        nl.Facts(behavior_date=date(2025, 6, 1), decision_date=date(2025, 6, 2),
                 behavior_type="参与赌博", region="330100"),
    ]
    for case in cases:
        a = nl.assess(case)
        r = a.stake_threshold
        assert r["hard_filter_allowed"] is False
        assert r["final_band_determinable"] is False
        assert a.exhaustive_for_case is False
        assert len(r["bands"]) == len(r["observed_band_indices"])
        if r["applicability"] == "unavailable":
            assert r["bands"] == r["band_penalty"] == []
        else:
            assert all(0 <= k <= 3 for k in r["observed_band_indices"])


@pytest.mark.parametrize("stake, status", [
    ({"min": 10000, "max": None}, "可能达到"),    # "赌资在万元以上"：开口，只能说可能达到 5 万门槛
    ({"min": 60000, "max": None}, "达到"),        # "6 万元以上"：下界已过门槛
    ({"min": 10000, "max": 19999}, None),         # 按数量级补上界会把它错判成未达到（不提示）
])
def test_referral_open_upper_bound(stake, status):
    a = nl.assess(to_facts({"behavior_date": date(2026, 3, 1), "behavior_type": "为赌博提供条件",
                            "cumulative_stake": stake}))
    got = [r["status"] for r in a.referral if r["item"] == "cumulative_stake"]
    assert got == ([status] if status else [])


def test_every_option_respects_statutory_maximum():
    """红线 R1 的结构性保证：任何选项都不超过所在档次的法定上限。"""
    lib = load()
    for case in GOLDEN["cases"]:
        a = nl.assess(to_facts(case["facts"]))
        law = lib.law(a.law_id)
        for name, tr in a.tiers.items():
            t = law.tiers[name]
            for o in tr.options:
                assert o.detention is None or o.detention[1] <= t.detention[1]
                assert o.fine is None or o.fine[1] <= t.fine[1]


@pytest.mark.parametrize("form, bands", [
    ("聚众赌博", ["第二档"]),     # 聚众类：500–1000 元为第二档（5 日以下拘留）
    ("赌场赌博", ["第二档"]),
    ("其他", ["第一档"]),         # 其他赌博活动：500–2000 元为第一档（罚款）
    (None, ["第一档", "第二档"]),  # 组织形式不明：两类门槛取并集
])
def test_jiangsu_category_by_gambling_form(form, bands):
    r = nl.assess(nl.Facts(behavior_date=date(2023, 5, 1), decision_date=date(2023, 5, 10), region="320582",
                           behavior_type="参与赌博", method="麻将", gambling_form=form,
                           personal_stake=AmountRange(min=600, max=600))).stake_threshold
    assert r["bands"] == bands


def test_online_method_wins_over_form():
    r = nl.assess(nl.Facts(behavior_date=date(2023, 5, 1), decision_date=date(2023, 5, 10), region="320582",
                           behavior_type="参与赌博", method="网络赌博", gambling_form="其他",
                           personal_stake=AmountRange(min=600, max=600))).stake_threshold
    assert r["bands"] == ["第二档"]

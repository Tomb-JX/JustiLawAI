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
    ({"method": "麻将", "personal_stake": {"min": 50, "max": 50}}, "未达到赌资较大", ["未达起罚标准"]),
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
    # 第 121 条"一场赌资……或者个人赌资……"：个人 300（较轻），一场 1500（一般）→ 取较高档
    ({"personal_stake": {"min": 300, "max": 300}, "onsite_stake_total": {"min": 1500, "max": 1500}}, ["一般情节"]),
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
    assert any("数额衔接待法律组核验" in n for n in a.stake_threshold["notes"])


def test_jiangsu_provide_conditions_bands():
    r = nl.assess(nl.Facts(behavior_date=date(2025, 6, 1), behavior_type="为赌博提供条件", region="320582",
                           commission=AmountRange(min=300, max=300), times=3)).stake_threshold
    assert r["status"] == "档次确定" and r["bands"] == ["第三档"]   # 获利 300（第二档）与 3 次（第三档）取较高


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

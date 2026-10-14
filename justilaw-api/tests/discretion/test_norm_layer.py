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
    assert lib.cite("spc-spp-2005-gambling", "1") is None   # 未取得原文，不得引用


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

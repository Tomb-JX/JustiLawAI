"""逐条台账（ADR-010 决定 4）：每部已录入的省级基准都要有台账；台账与原文逐条一致、处置齐全、引用可解析；复核表与台账同步。"""
from pathlib import Path

import pytest
import yaml

from app.discretion import ledger as L
from app.discretion.norm_store import NORMS_DIR
from app.discretion.schema import iter_fields

FIELDS = {p for p, _, _ in iter_fields()}
PROVINCES = sorted(p.stem for p in (NORMS_DIR / "provinces").glob("*.yaml") if not p.stem.startswith("_"))
# 暂缺台账的省份必须写明原因（Q-28）；补齐后从这里删除
PENDING = {"130000": "规则库只存了第 121 条等节选（869 字），须先补全河北基准原文再建台账"}
REPORTS = Path(__file__).resolve().parents[3] / "docs/06-algorithm/ledgers"


def _prov(code):
    return yaml.safe_load((NORMS_DIR / "provinces" / f"{code}.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", PROVINCES)
def test_every_province_has_complete_ledger(code):
    if code in PENDING:
        assert not (L.LEDGER_DIR / f"{code}.yaml").exists(), f"{code} 已有台账，请从 PENDING 删除"
        pytest.skip(PENDING[code])
    prov = _prov(code)
    errs = L.check(L.load(code), prov["documents"][0]["text"], prov, FIELDS)
    assert not errs, "\n".join(errs)


@pytest.mark.parametrize("code", PROVINCES)
def test_segmenter_reassembles_source(code):
    text = _prov(code)["documents"][0]["text"]
    assert L._squash("".join(s.text for s in L.segment(text))) == L._squash(text)


def test_ledger_detects_drift():
    prov = _prov("320000")
    led = L.load("320000")
    led["items"][20]["text"] += "（改写）"
    led["items"][30]["disposition"] = None
    led["items"][31]["refs"] = ["rules.参与赌博.measures.不存在"]
    errs = L.check(led, prov["documents"][0]["text"], prov, FIELDS)
    assert any("条目文字" in e for e in errs) and any("处置缺失" in e for e in errs) and any("无法解析" in e for e in errs)


@pytest.mark.parametrize("name", sorted(L.all_ledgers()))
def test_review_sheet_in_sync(name):
    assert (REPORTS / f"{name}.md").read_text(encoding="utf-8") == L.to_markdown(L.load(name)), \
        "复核表过期：运行 python scripts/ledger_report.py"


def test_jiangsu_cumulative_stake_bands_by_clause():
    """台账 一.（三）（五）：只有累计赌资时按累计赌资定档，计算过程引用条款。"""
    from datetime import date

    from app.discretion.norm_layer import Facts, assess
    from app.discretion.schema import AmountRange
    base = dict(behavior_date=date(2022, 5, 1), decision_date=date(2022, 6, 1), region="320500",
                behavior_type="参与赌博", method="网络赌博")
    st = assess(Facts(**base, cumulative_stake=AmountRange(min=600, max=600))).stake_threshold
    m = [c for c in st["computation"] if c["step"] == "measure"][0]
    assert st["bands"] == ["第二档"] and "第一节（三）" in m["basis_of_value"]
    both = assess(Facts(**base, personal_stake=AmountRange(min=200, max=200),
                        cumulative_stake=AmountRange(min=1500, max=1500))).stake_threshold
    assert both["bands"] == ["第三档"]           # 累计优先于单次
    hebei = assess(Facts(**{**base, "region": "130100", "behavior_date": date(2022, 5, 1)},
                         cumulative_stake=AmountRange(min=600, max=600))).stake_threshold
    assert "cumulative" not in str([c.get("basis_of_value") for c in hebei["computation"]])   # 河北原文无条款，不用

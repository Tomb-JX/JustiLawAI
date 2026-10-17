"""标注一致性（agreement.py）：三种口径的差别、判定规则、取值规范化。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agreement as A  # noqa: E402

ABS = {"value": None, "status": "未提及", "evidence": []}


def v(x, status="明确"):
    return {"value": x, "status": status, "evidence": ["原文"]}


def rec(i, **fields):
    return {"id": i, "fields": {k.replace("__", "."): f for k, f in fields.items()}}


def as_map(rows):
    return {r["id"]: A.flatten(r) for r in rows}


def test_union_excludes_both_absent_but_all_counts_them():
    # 10 件：8 件双方都未提及，1 件一致为"是"，1 件一方"是"一方未提及
    a = [rec(f"r{i}", intent__profit_purpose=ABS) for i in range(8)] + \
        [rec("r8", intent__profit_purpose=v(True)), rec("r9", intent__profit_purpose=v(True))]
    b = [rec(f"r{i}", intent__profit_purpose=ABS) for i in range(8)] + \
        [rec("r8", intent__profit_purpose=v(True)), rec("r9", intent__profit_purpose=ABS)]
    f = A.field_agreement(as_map(a), as_map(b), "intent.profit_purpose", [f"r{i}" for i in range(10)])
    assert f["n_union"] == 2 and f["agree_union"] == 0.5
    assert f["agree_all"] == 0.9                      # all 口径被"双方都未提及"抬到 90%
    assert f["n_valued"] == 1 and f["agree_valued"] == 1.0   # valued 口径看不出漏标
    assert f["absent_agreement"] == pytest.approx(8 / 9)
    assert f["disagreements"] == ["r9"]


def test_amount_open_upper_only_matches_open():
    a = as_map([rec("x", amounts__personal_stake=v({"min": 10000, "max": None}))])
    b = as_map([rec("x", amounts__personal_stake=v({"min": 10000, "max": 99999}))])
    assert A.field_agreement(a, b, "amounts.personal_stake", ["x"])["agree_union"] == 0.0
    b = as_map([rec("x", amounts__personal_stake=v({"min": 10000.0, "max": None}))])
    assert A.field_agreement(a, b, "amounts.personal_stake", ["x"])["agree_union"] == 1.0


def test_gate_uses_union_and_reports_contrast():
    roles = ["参赌者", "提供条件者", "组织者", "参赌者", "参赌者", "提供条件者"]
    a = [rec(f"r{i}", conduct__role=v(r), persons__participant_count=v(4)) for i, r in enumerate(roles)]
    b = [rec(f"r{i}", conduct__role=v(r), persons__participant_count=v(4 if i else 5)) for i, r in enumerate(roles)]
    rep = A.agreement(as_map(a), as_map(b))
    g = rep["gate"]
    assert g["key_categorical_fields_used"] == ["conduct.role"]
    assert g["key_categorical_mean_kappa"] == pytest.approx(1.0)
    assert g["key_numeric_pairs"] == 6 and g["key_numeric_exact_rate"] == pytest.approx(5 / 6)
    assert g["pass"] is False                          # 数值 83% < 95%
    excluded = {e["field"] for e in g["key_categorical_excluded"]}
    assert {"conduct.behavior_type", "intent.profit_purpose"} <= excluded   # 配对不足，不进平均
    assert "all" in rep["contrast"] and "valued" in rep["contrast"]


def test_nested_format_and_cli(tmp_path):
    row = {"id": "n1", "conduct": {"role": v("参赌者")}, "amounts": {"commission": v({"min": 60, "max": 60})}}
    for name in ("a", "b"):
        (tmp_path / f"{name}.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", "utf-8")
    code = A.main([str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl"), "--out", str(tmp_path / "out"),
                   "--names", "deepseek-flash", "qwen3.8-max"])
    rep = json.loads((tmp_path / "out" / "agreement.json").read_text("utf-8"))
    assert rep["records_common"] == 1 and rep["annotators"] == ["deepseek-flash", "qwen3.8-max"]
    assert code == 1                                   # 只有 1 件，分类字段配对不足，不能判通过

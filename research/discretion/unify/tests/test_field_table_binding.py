"""find_person_binding 单测：页头 person 栏 ↔ 目标人确定性绑定（2026-10-25 金丝雀配套）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from field_table import find_person_binding  # noqa: E402


def _rec(lines):
    text = "\n".join(lines)
    sentences = []
    pos = 0
    for ln in lines:
        sentences.append([pos, pos + len(ln)])
        pos += len(ln) + 1
    return {"cleaned_text": text, "sentences": sentences}


def _out(spec):
    return {"zones": [{"type": t, "from": a, "to": b} for t, a, b in spec]}


_ZONES = [("meta", 1, 2), ("facts", 3, 3), ("decision", 4, 4)]


def test_field_table_mask_variant_binds():
    rec = _rec(["行政相对人：王*乙", "执法机关：某区公安分局",
                "2024年3月，王x乙在棋牌室赌博。", "处罚种类：罚款"])
    f = find_person_binding(rec, _out(_ZONES), "王x乙")
    assert f is not None and f["label"] == "行政相对人" and f["value"] == "王*乙"


def test_real_name_header_binds_masked_target():
    rec = _rec(["行政相对人：曾红权", "执法机关：某县公安局",
                "2024年3月，曾**参与赌博。", "执法依据：程序规定第172条"])
    f = find_person_binding(rec, _out(_ZONES), "曾**")
    assert f is not None and f["value"] == "曾红权"


def test_different_person_not_bound():
    rec = _rec(["行政相对人：王*乙", "执法机关：某区公安分局",
                "2024年3月，王x乙在棋牌室赌博。", "处罚种类：罚款"])
    assert find_person_binding(rec, _out(_ZONES), "王大明") is None


def test_multi_person_column_binds_member():
    rec = _rec(["行政相对人：张三、李四等2人", "执法机关：某区公安分局",
                "2024年3月，张三与李四赌博。", "处罚种类：罚款"])
    f = find_person_binding(rec, _out(_ZONES), "李四")
    assert f is not None


def test_identity_prefix_value_contains_target():
    rec = _rec(["违法行为人：李**，男，年龄45岁", "执法机关：某区公安分局",
                "2024年3月，李**在棋牌室赌博。", "处罚种类：行政拘留"])
    f = find_person_binding(rec, _out(_ZONES), "李**")
    assert f is not None


def test_no_person_field_returns_none():
    rec = _rec(["执法机关：某区公安分局", "处罚机关：某区公安分局",
                "2024年3月，王x乙赌博。", "处罚种类：罚款"])
    assert find_person_binding(rec, _out(_ZONES), "王x乙") is None


def test_empty_target_returns_none():
    rec = _rec(["行政相对人：王*乙", "执法机关：某区公安分局",
                "2024年3月，王x乙赌博。", "处罚种类：罚款"])
    assert find_person_binding(rec, _out(_ZONES), "") is None

"""试标抽样单测：合成记录（无正文、无真实案例），不联网、不读外置数据目录。

运行（仓库根目录）：python -m pytest research/discretion/harvest/tests -q
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sample_pilot import OTHER, PILOT_FIELDS, allocate, main, plan, province_groups, raise_floor  # noqa: E402

_seq = iter(range(10**6))


def rec(province="河北省", source_type="处罚决定书", law="旧法", amount=False, outcome="拘留", event=None,
        ambiguous=False, variants=0) -> dict:
    i = next(_seq)
    rid = f"W-{i:06d}"
    facts = f"甲在某村赌博{i}。"
    return {
        "id": rid, "event_id": event or f"E-{i}", "province": province, "source_type": source_type,
        "law_version": law, "subject_alias": "甲", "behavior_date": "2025-06", "schema_version": "1.0.0",
        "region": "130626", "doc_no_hash": "0" * 16, "authority": "某县公安局",
        "text_full": facts, "text_sha256": "x", "text_facts": facts, "text_evidence": "", "text_reasoning": "",
        "text_decision": "", "text_review": "", "segments": {"text_facts": [0, len(facts)]},
        "outcome": {"type": outcome, "law_version": law}, "review": {"result": "无", "changed_outcome": None},
        "quality": {"completeness": {"has_amount": amount, "has_outcome": True}, "ambiguous_persons": ambiguous,
                    "subject_variants": variants},
    }


def corpus() -> list[dict]:
    """缩小版首批分布：大省两个、目标省三个（含新法）、零星省份若干、多人同案事件。"""
    rs = []
    for k in range(60):
        rs.append(rec("广西壮族自治区", amount=k % 3 == 0))
    for k in range(50):
        rs.append(rec("河北省", amount=k % 2 == 0))
    for k in range(20):
        rs.append(rec("安徽省", "执法公示", amount=k < 10))
    for _ in range(12):
        rs.append(rec("云南省", "执法公示"))
    for _ in range(6):
        rs.append(rec("云南省", "执法公示", law="新法"))
    for _ in range(4):
        rs.append(rec("浙江省", "行政复议决定书", amount=True))
    for p in ("重庆市", "湖北省", "山东省"):
        rs.append(rec(p, amount=True))
    # 多人同案：同一事件 5 件，只能出 1 件
    rs += [rec("河北省", event="E-group", amount=True) for _ in range(5)]
    # 不予处罚 2 件
    rs.append(rec("安徽省", "执法公示", outcome="不予处罚", amount=True))
    rs.append(rec("广西壮族自治区", outcome="不予处罚"))
    # 不可抽
    rs += [rec("浙江省", "行政复议决定书", amount=True, ambiguous=True) for _ in range(3)]
    rs += [rec("云南省", "执法公示", law="新法", variants=1) for _ in range(3)]
    return rs


def test_allocate_sums_and_respects_floor_and_cap():
    avail = {"a": 100, "b": 50, "c": 2, "d": 1}
    weight = dict(avail)
    q = allocate(avail, weight, {"a": 1, "b": 1, "c": 1, "d": 1}, 20)
    assert sum(q.values()) == 20
    assert all(1 <= q[s] <= avail[s] for s in avail)
    assert q["a"] > q["b"] > q["c"]
    # 下限触发
    q = allocate(avail, weight, {"a": 1, "b": 1, "c": 2, "d": 1}, 20)
    assert q["c"] == 2 and sum(q.values()) == 20
    # 上限触发：权重很大的小层不超过可抽数
    q = allocate({"a": 3, "b": 100}, {"a": 1000, "b": 1}, {}, 10)
    assert q == {"a": 3, "b": 7}
    # 样本量超过总可抽数：全取
    assert allocate({"a": 2, "b": 3}, {"a": 1, "b": 1}, {}, 50) == {"a": 2, "b": 3}


def test_allocate_rejects_infeasible_floors():
    try:
        allocate({"a": 5, "b": 5}, {"a": 1, "b": 1}, {"a": 4, "b": 4}, 6)
    except ValueError:
        return
    raise AssertionError("下限合计超过样本量应报错")


def test_raise_floor_spreads_from_largest():
    floor, avail = {"x": 1, "y": 1, "z": 0}, {"x": 10, "y": 2, "z": 1}
    raise_floor(floor, avail, ["x", "y", "z"], 5)
    assert sum(floor.values()) == 5 and floor["y"] <= 2 and floor["z"] <= 1
    floor = {"x": 0}
    raise_floor(floor, {"x": 2}, ["x"], 5)   # 可抽不够时取尽为止
    assert floor["x"] == 2


def test_province_groups_folds_small_non_target():
    reps = [{"province": "河北省"}] * 12 + [{"province": "浙江省"}] * 2 + [{"province": "重庆市"}] * 3 + [{"province": ""}]
    g = province_groups(reps)
    assert g["河北省"] == "河北省" and g["浙江省"] == "浙江省"   # 目标省再少也单独成层
    assert g["重庆市"] == OTHER and g[""] == OTHER


def test_plan_rules():
    rs = corpus()
    picked, report = plan(rs, n=30, seed="t")
    ids = [r["id"] for r in picked]
    assert len(picked) == 30 and len(set(ids)) == 30
    # 一事件一件
    assert len({r["event_id"] for r in picked}) == 30
    # 不可抽的一件不进
    assert all(not r["quality"]["ambiguous_persons"] and not r["quality"]["subject_variants"] for r in picked)
    # 不予处罚全收
    assert sum(r["outcome"]["type"] == "不予处罚" for r in picked) == 2
    # 新法至少 5、每个目标省至少 5（浙江可抽只有 4 件，取尽）
    assert sum(r["law_version"] == "新法" for r in picked) >= 5
    by_p = {p: sum(r["province"] == p for r in picked) for p in ("安徽省", "云南省", "浙江省")}
    assert by_p["安徽省"] >= 5 and by_p["云南省"] >= 5 and by_p["浙江省"] == 4
    # 每层至少 1 件："其他"层也有
    assert all(s["quota"] >= 1 for s in report["strata"])
    assert any(s["province"] == OTHER for s in report["strata"])
    assert sum(s["quota"] for s in report["strata"]) == 30
    # 有金额优先：层内还有没抽中的有金额事件时，抽中的（不予处罚除外）不会无金额
    picked_events = {r["event_id"] for r in picked}
    for s in {(r["province"], r["source_type"], r["law_version"]) for r in picked}:
        inside = [r for r in rs if (r["province"], r["source_type"], r["law_version"]) == s
                  and not r["quality"]["ambiguous_persons"] and not r["quality"]["subject_variants"]]
        amount_left = any(r["quality"]["completeness"]["has_amount"] and r["event_id"] not in picked_events for r in inside)
        no_amount_picked = [r for r in inside if r["id"] in ids and r["outcome"]["type"] != "不予处罚"
                            and not r["quality"]["completeness"]["has_amount"]]
        assert not (amount_left and no_amount_picked), s


def test_plan_is_deterministic_and_order_free():
    rs = corpus()
    a, _ = plan(rs, n=30, seed="t")
    shuffled = rs[:]
    random.Random(7).shuffle(shuffled)
    b, _ = plan(shuffled, n=30, seed="t")
    assert [r["id"] for r in a] == [r["id"] for r in b]
    c, _ = plan(rs, n=30, seed="another")
    assert [r["id"] for r in a] != [r["id"] for r in c]


def test_main_writes_annotation_fields_only(tmp_path):
    src = tmp_path / "admin_cases.jsonl"
    src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in corpus()), encoding="utf-8")
    out = tmp_path / "pilot.jsonl"
    assert main(["--input", str(src), "--out", str(out), "--n", "20", "--seed", "t"]) == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 20
    for r in rows:
        assert tuple(r) == PILOT_FIELDS
        assert "quality" not in r and "region" not in r and "doc_no_hash" not in r and "authority" not in r
    stats = json.loads((tmp_path / "pilot.stats.json").read_text(encoding="utf-8"))
    assert stats["ids"] == [r["id"] for r in rows]
    assert len(stats["input_sha256"]) == 64 and len(stats["output_sha256"]) == 64
    assert "text_full" not in json.dumps(stats, ensure_ascii=False)

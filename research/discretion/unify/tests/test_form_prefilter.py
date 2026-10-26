"""form 八值判别 + 预筛 v2（borderline / 分层抽样确定性 / 并集词表）单测（姓名虚构）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from form import detect_form  # noqa: E402
from prefilter import eval_prefilter, sample_pool, GAMBLING_UNION  # noqa: E402


# ---------- form ----------

def test_form_review_and_judgment():
    assert detect_form("行政复议决定书", "任何文本") == "叙述式-复议"
    assert detect_form("行政判决书", "任何文本") == "判决书"


def test_form_narrative():
    assert detect_form("处罚决定书", "经查，张某某某赌博。", "") == "叙述式-独立成篇"
    # pkulaw 真值直接复用
    assert detect_form("处罚决定书", "任意", "叙述式-结果栏内") == "叙述式-结果栏内"


def test_form_field_table():
    t = "案件名称：赌博案\n违法事实：张某某赌博\n处罚结果：罚款五百元\n决定书文号：某公（行）行罚决字〔2023〕1号"
    assert detect_form("执法公示", t) == "字段表公示"


def test_form_title_summary():
    t = "李某某等人赌博案\n2023.5.8\n某县公安局\n赌资较大\n罚款五百元"
    assert detect_form("执法公示", t) == "标题汇总公示"


def test_form_mixed():
    t = "案件名称：赌博案\n张某某在某处赌博被处罚"
    assert detect_form("执法公示", t) == "混合-弱模板"


# ---------- 预筛 ----------

def _rec(gamb="是", authority="某县公安局", decision="决定给予行政拘留十日", text="经查张某某赌博。", extra=None):
    return {"id": "X-1", "text_facts": "", "text_decision": decision, "text_review": "",
            "authority": authority, "extra": extra or {},
            "quality": {"gambling": gamb, "in_scope": True}}


def test_borderline_cite_abbrev():
    # 有公安、无治安法全称 → cite_abbrev（实测 56 件类）
    p = eval_prefilter(_rec(), "经查张某某赌博。决定给予行政拘留十日。")
    assert p["borderline"] == "cite_abbrev" and p["release"] is True


def test_borderline_authority_ctx():
    # 无公安、有治安法 → authority_ctx（实测 16 件类）
    p = eval_prefilter(_rec(authority="某县市场监督管理局",
                            decision="依据治安管理处罚法第七十条作出处理。"), "")
    assert p["borderline"] == "authority_ctx"


def test_no_borderline_full_match():
    p = eval_prefilter(_rec(), "依据治安管理处罚法第七十条决定给予行政拘留十日。")
    assert p["borderline"] == "" and p["release"] is True and p["release_reason"] == "gamb:是"


def test_pending_released():
    p = eval_prefilter(_rec(gamb="待定"), "内容")
    assert p["release"] is True and p["release_reason"] == "gamb:待定"


def test_union_wordlist():
    assert GAMBLING_UNION.search("以牌九方式赌博")
    assert GAMBLING_UNION.search("设置老虎机")
    assert GAMBLING_UNION.search("参与斗地主赌博以积分为筹码凭输赢结算")


# ---------- 抽样确定性 ----------

def _pool(n_per=20):
    strata = ["A_前科句式", "B_简写引证", "C_判定区涉赌词", "D_其余"]
    out = []
    for si, s in enumerate(strata):
        for k in range(n_per):
            out.append({"id": f"X-{si}-{k:02d}", "_unified": {"prefilter": {"stratum": s}}})
    return out


def test_sample_deterministic():
    pool = _pool()
    a = sample_pool(pool, target=30, seed=42)
    b = sample_pool(pool, target=30, seed=42)
    assert a == b and len(a) == 30


def test_sample_priority_edge_strata():
    pool = _pool(n_per=20)
    picked = sample_pool(pool, target=45, seed=1)  # 边缘层 60 件 > 目标：只从边缘层抽
    assert len(picked) == 45
    assert not any(i.startswith("X-3-") for i in picked)  # D 层不进


def test_sample_fills_rest():
    pool = _pool(n_per=5)  # 边缘层 15 件 < 目标
    picked = sample_pool(pool, target=20, seed=1)
    assert len(picked) == 20
    assert sum(1 for i in picked if i.startswith("X-3-")) == 5  # D 层补齐


def test_norm_page_blocked_even_when_yes():
    # 程序性清单页（min-40 队列 W-000648-45 型）：gambling=是 也不放行
    rec = {"id": "X-n1", "authority": "某某市文化市场综合行政执法支队",
           "text_decision": "", "text_review": "", "text_facts": "",
           "quality": {"gambling": "是", "in_scope": True}}
    p = eval_prefilter(rec, "对为赌博提供条件等两类行为的处罚 行使该职权的责任：依法查处 送达阶段责任：决定书应依法送达")
    assert p["norm_page"] is True and p["release"] is False and p["release_reason"] == "norm_page"

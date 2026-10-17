"""S3 校验注册表单测：两级罚幅对账 / 类型一致性 / 日期顺序 / subject / 重叠（合成 ctx，无 API）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from s3 import (check_penalty_caps, check_outcome_consistency, check_dates,  # noqa: E402
                check_subject, check_decision_present, run_checks)


def _ctx(outcome=None, dates=None, subject=None, segments=None, rec=None):
    return {
        "record": rec or {"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                          "behavior_date": "2023-05", "decision_date": "2023-06"},
        "output": {"outcome": outcome or {}, "dates": dates or {}, "subject": subject or {},
                   "segments": segments or [], "gambling": {"verdict": "是"}, "confidence": "high",
                   "review": {"result": "无", "changed_outcome": None}},
        "locates": {}, "disambiguated": {},
    }


def _sev(findings):
    return {(f.check, f.severity) for f in findings}


# ---------- 两级罚幅对账 ----------

def test_caps_single_within():
    out = {"outcome": {"type": "拘留并处罚款", "detention_days": 12, "fine": 2000,
                       "multi_violation": False,
                       "articles": [{"text": "治安管理处罚法第七十条", "edition": "2012修正"}]}}
    assert not check_penalty_caps(_ctx(out))


def test_caps_single_exceeded_error():
    out = {"type": "拘留并处罚款", "detention_days": 18, "fine": 4000,
           "multi_violation": False,
           "articles": [{"text": "第七十条", "edition": "2012修正"}]}
    f = check_penalty_caps(_ctx(out))
    assert ("penalty_caps", "error") in _sev(f)


def test_caps_unknown_edition_warn_not_error():
    out = {"type": "拘留并处罚款", "detention_days": 15, "fine": 4000,
           "multi_violation": False,
           "articles": [{"text": "第七十条", "edition": "未知"}]}
    assert ("penalty_caps", "warn") in _sev(check_penalty_caps(_ctx(out)))


def test_caps_art16_hard_limit():
    # 任何情形拘留合计 >20 日都是硬越限（第十六条）
    out = {"type": "拘留", "detention_days": 25, "fine": 0,
           "multi_violation": True,
           "executed_penalty": {"detention_days": 25, "fine": 0},
           "articles": [{"text": "第七十条", "edition": "2012修正"}]}
    f = check_penalty_caps(_ctx(out))
    assert ("penalty_caps", "error") in _sev(f)


def test_caps_merged_within_art16():
    out = {"type": "拘留并处罚款", "detention_days": 20, "fine": 5000,
           "multi_violation": True,
           "executed_penalty": {"detention_days": 20, "fine": 5000},
           "articles": [{"text": "第七十条", "edition": "2012修正"}]}
    assert not check_penalty_caps(_ctx(out))


def test_caps_2025_hard_after_caps_table():
    # 常量表（legal_caps.json）就位后 2025修订硬对账：单行为罚款上限 5000
    out = {"type": "罚款", "detention_days": 0, "fine": 6000,
           "multi_violation": False,
           "articles": [{"text": "第八十二条", "edition": "2025修订"}]}
    assert ("penalty_caps", "error") in _sev(check_penalty_caps(_ctx(out)))
    ok = {"type": "罚款", "detention_days": 0, "fine": 4500,
          "multi_violation": False,
          "articles": [{"text": "第八十二条", "edition": "2025修订"}]}
    assert not [f for f in check_penalty_caps(_ctx(ok)) if f.severity == "error"]


def test_article_edition_binding():
    from s3 import check_article_edition
    bad = _ctx({"type": "罚款", "detention_days": 0, "fine": 500,
                "articles": [{"text": "治安管理处罚法第八十二条", "edition": "2012修正"}]})
    assert any(f.check == "article_edition" and f.severity == "error" for f in check_article_edition(bad))
    good = _ctx({"type": "罚款", "detention_days": 0, "fine": 500,
                 "articles": [{"text": "治安管理处罚法第七十条", "edition": "2012修正"}]})
    assert check_article_edition(good) == []


# ---------- 类型一致性 ----------

def test_outcome_matrix():
    assert not check_outcome_consistency(_ctx({"type": "拘留并处罚款", "detention_days": 5, "fine": 500}))
    assert check_outcome_consistency(_ctx({"type": "拘留", "detention_days": 0, "fine": 0}))
    assert check_outcome_consistency(_ctx({"type": "罚款", "detention_days": 5, "fine": 500}))
    assert check_outcome_consistency(_ctx({"type": "不予处罚", "detention_days": 3, "fine": 0}))


# ---------- 日期顺序 ----------

def test_dates_order():
    f = check_dates(_ctx(rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                              "behavior_date": "2023-06", "decision_date": "2023-06"}))
    assert not any(x.severity == "error" for x in f)
    f = check_dates(_ctx(rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                              "behavior_date": "2023-08", "decision_date": "2023-06"}))
    assert ("dates_order", "error") in _sev(f)


# ---------- subject ----------

def test_subject_must_be_in_facts():
    segs = [{"type": "facts", "quote": "张某某在某棋牌室赌博"},
            {"type": "decision", "quote": "决定给予行政拘留十日"}]
    assert not check_subject(_ctx(subject={"mention": "张某某"}, segments=segs))
    assert check_subject(_ctx(subject={"mention": "李某某"}, segments=segs))


# ---------- decision 段存在 ----------

def test_decision_required_when_outcome_present():
    segs = [{"type": "facts", "quote": "张某某赌博"}]
    out = {"type": "拘留", "detention_days": 5, "fine": 0}
    assert check_decision_present(_ctx(outcome=out, segments=segs))


# ---------- 全注册表冒烟 ----------

def test_run_checks_smoke():
    segs = [{"type": "facts", "quote": "张某某在某棋牌室赌博"},
            {"type": "decision", "quote": "决定给予行政拘留十日"}]
    out = {"segments": segs, "subject": {"mention": "张某某", "aliases": []},
           "outcome": {"type": "拘留并处罚款", "detention_days": 10, "fine": 1500,
                       "not_executed": "否", "multi_violation": False,
                       "executed_penalty": {"detention_days": 0, "fine": 0},
                       "confiscation": [], "detention_items": [],
                       "articles": [{"text": "第七十条", "edition": "2012修正"}],
                       "stated_circumstances": []},
           "dates": {"behavior": {"quote": None}, "decision": {"quote": None}},
           "review": {"result": "无", "changed_outcome": None},
           "gambling": {"verdict": "是", "reason": "赌博"}, "confidence": "high"}
    findings = run_checks(_ctx(outcome=out["outcome"], dates=out["dates"],
                               subject=out["subject"], segments=segs))
    errors = [f for f in findings if f.severity == "error"]
    # 合法样例不应有任何 error（warn 可有：日期未给）
    assert not errors, [f.detail for f in errors]


# ---------- 覆盖度（协同指令 §3c） ----------

def test_coverage_sparse_error():
    from s3 import check_coverage
    from locate import Located
    ctx = {"record": {"form": "叙述式-独立成篇"},
           "locates": {"seg:facts": Located("exact_unique", 0, 30),
                       "seg:decision": Located("exact_unique", 40, 70)}}
    f = check_coverage(ctx)   # 并集 60 / 区间 70 = 86% < 95%
    assert any(x.check == "coverage" and x.severity == "error" for x in f)


def test_coverage_dense_pass():
    from s3 import check_coverage
    from locate import Located
    ctx = {"record": {"form": "叙述式-独立成篇"},
           "locates": {"seg:facts": Located("exact_unique", 0, 50),
                       "seg:decision": Located("exact_unique", 50, 100)}}
    assert check_coverage(ctx) == []


def test_caps_loader_prefers_config():
    from s3 import _load_caps
    caps = _load_caps()   # 数据目录暂无 legal_caps.json → 内置口径
    assert "2012修正" in caps

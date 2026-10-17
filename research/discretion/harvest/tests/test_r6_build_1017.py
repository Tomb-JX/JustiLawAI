"""r6 构建改造回归测试（协同指令 2026-10-17 §2；样例全部虚构）：
B 类定性句裁剪、build_record 原文正本契约（零遮蔽字段）、subject_mention 纳入、fine_masked 豁免。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "discover"))

from parse import CONCLUSION_MARK, trim_facts_conclusions  # noqa: E402
from build import build_record, from_parsed1, inclusion  # noqa: E402
from regions import Resolver, load_table  # noqa: E402


# ---------- B 类裁剪 ----------

def test_trim_trailing_conclusions():
    f, c = trim_facts_conclusions("张某某在某棋牌室赌博。情节严重。决定给予行政拘留十日。")
    assert c and f == "张某某在某棋牌室赌博。"


def test_trim_interior_kept():
    # 内部混入的结论句不动（facts 保持原文连续子串），旗标由 facts_contains_conclusion 豁免
    f, c = trim_facts_conclusions("张某某在某棋牌室赌博，情节严重，赌资五千元。后被查获。")
    assert not c and f == "张某某在某棋牌室赌博，情节严重，赌资五千元。后被查获。"


def test_trim_all_conclusion_untouched():
    f, c = trim_facts_conclusions("决定给予行政拘留十日。")
    assert not c and f == "决定给予行政拘留十日。"


def test_conclusion_mark_words():
    for w in ("决定给予", "现决定", "减轻处罚", "不予处罚", "已构成"):
        assert CONCLUSION_MARK.search(w)


# ---------- build_record 原文正本契约 ----------

def _rec(**kw):
    base = {
        "id": "W-990001", "source_type": "处罚决定书",
        "doc_no": "某公（行）行罚决字〔2023〕99号",
        "harvest_date": "2026-10-16", "behavior_date": "2023-05-01", "decision_date": "2023-05-02",
        "authority": "某县公安局", "subject_mention": "张某某",
        "text_full": "经查，张某某在某棋牌室赌博。决定给予行政拘留五日。",
        "text_facts": "经查，张某某在某棋牌室赌博。", "text_evidence": "", "text_reasoning": "",
        "text_decision": "决定给予行政拘留五日。", "text_review": "",
        "segmented": True, "outcome": {"type": "拘留", "detention_days": 5, "fine": 0,
                                        "articles": ["治安管理处罚法第七十条"], "law_version": "旧法"},
        "review": {"result": "无"}, "parse_warnings": [], "completeness": {"has_amount": True},
        "ocr": False, "site": "s", "_region": None,
    }
    base.update(kw)
    return base


def test_build_record_no_deid_fields():
    out, trimmed = build_record(_rec())
    for gone in ("deidentified", "r6_scan", "subject_alias"):
        assert gone not in out
    assert out["doc_no"] == "某公（行）行罚决字〔2023〕99号"      # 文号明文（D3 放宽）
    assert out["subject_mention"] == "张某某"
    assert out["text_full"] == "经查，张某某在某棋牌室赌博。决定给予行政拘留五日。"
    assert out["text_sha256"]


def test_build_record_segments_are_substrings():
    out, _ = build_record(_rec())
    for f in ("text_facts", "text_decision"):
        a, b = out["segments"][f]
        assert out["text_full"][a:b] == out[f]


def test_build_record_b_trim_recomputes_flag():
    rec = _rec(text_full="经查，张某某在某棋牌室赌博。情节严重。决定给予行政拘留十日。",
               text_facts="经查，张某某在某棋牌室赌博。情节严重。",
               text_decision="决定给予行政拘留十日。",
               parse_warnings=["facts_contains_conclusion"])
    out, trimmed = build_record(rec)
    assert trimmed
    assert out["text_facts"] == "经查，张某某在某棋牌室赌博。"
    assert "facts_contains_conclusion" not in out["quality"]["parse_warnings"]
    assert not out["quality"]["facts_contains_conclusion"]


# ---------- inclusion（subject_mention 口径） ----------

def test_inclusion_subject_mention():
    out, _ = build_record(_rec())
    assert not [m for m in inclusion(out) if "本人" in m]
    out2, _ = build_record(_rec(subject_mention=""))
    assert "本人不可指认" in inclusion(out2)
    # 修订案 §B：mention 不在 facts 字面出现不再是排除条件（正文以"违法行为人"指代为合法形态）
    out3, _ = build_record(_rec(subject_mention="李某某"))
    assert not [m for m in inclusion(out3) if "本人" in m]


# ---------- fine_masked 豁免（P-715–717 口径） ----------

def test_from_parsed1_masked_fine_rescue():
    resolver = Resolver(load_table())
    rec = {
        "id": "P-990001", "source": "法宝执法库", "source_type": "处罚决定书",
        "doc_no": "某公行罚决字〔2021〕1号", "harvest_date": "2026-10-16",
        "behavior_date": "2021-03-01", "decision_date": "2021-03-05",
        "authority": "某省某县公安局", "province": "某省",
        "subject_mention": "陈某某",
        "text_full": "经查，陈某某以麻将牌九方式进行赌博。根据《治安管理处罚法》第七十条，决定罚款＊＊＊＊元。",
        "text_facts": "经查，陈某某以麻将牌九方式进行赌博。",
        "text_decision": "决定罚款＊＊＊＊元。", "text_review": "",
        "segmented": True,
        "outcome": {"type": "", "detention_days": 0, "fine": 0,
                    "articles": ["治安管理处罚法第七十条"], "law_version": "旧法"},
        "review": {"result": "无"},
        "law_version": "旧法",
        "quality": {"tier": "L1-金标候选", "in_scope": True, "gambling": "是",
                    "form": "叙述式-独立成篇", "parse_warnings": ["outcome_not_parsed"],
                    "completeness": {"has_amount": False, "has_outcome": False}},
        "extra": {"legacy": {"pkulaw_id": "t1"}},
    }
    got = from_parsed1(rec, resolver)
    assert got is not None
    assert got["outcome"]["type"] == "罚款"
    assert got["outcome"]["fine_masked"] is True
    assert got["outcome"]["fine"] == 0

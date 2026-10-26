"""S3 校验注册表单测（seg-v2 区间语义）：两级罚幅对账/条号-版本绑定/类型一致性/日期/subject/facts 质量族。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from s3 import (check_penalty_caps, check_outcome_consistency, check_dates,  # noqa: E402
                check_subject, check_decision_present, check_article_edition,
                check_facts_quality, run_checks)


def _ctx(outcome=None, dates=None, subject=None, zones=None, sentences=None, spans=None,
         cleaned="", rec=None):
    return {
        "record": rec or {"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                          "behavior_date": "2023-05", "decision_date": "2023-06",
                          "form": "叙述式-独立成篇", "cleaned_text": cleaned},
        "output": {"outcome": outcome or {}, "dates": dates or {}, "subject": subject or {},
                   "zones": zones or [], "gambling": {"verdict": "是"}, "confidence": "high",
                   "review": {"result": "无", "changed_outcome": None}},
        "sentences": sentences or [],
        "spans": spans or {},
        "locates": {}, "disambiguated": {},
    }


def _sev(findings):
    return {(f.check, f.severity) for f in findings}


# ---------- 两级罚幅对账 ----------

def test_caps_single_within():
    out = {"type": "拘留并处罚款", "detention_days": 12, "fine": 2000,
           "multi_violation": False,
           "articles": [{"text": "治安管理处罚法第七十条", "edition": "2012修正"}]}
    assert not check_penalty_caps(_ctx(out))


def test_caps_single_exceeded_error():
    out = {"type": "拘留并处罚款", "detention_days": 18, "fine": 4000,
           "multi_violation": False,
           "articles": [{"text": "第七十条", "edition": "2012修正"}]}
    assert ("penalty_caps", "error") in _sev(check_penalty_caps(_ctx(out)))


def test_caps_unknown_edition_warn():
    out = {"type": "拘留并处罚款", "detention_days": 15, "fine": 4000,
           "multi_violation": False,
           "articles": [{"text": "第七十条", "edition": "未知"}]}
    assert ("penalty_caps", "warn") in _sev(check_penalty_caps(_ctx(out)))


def test_caps_art16_hard_limit():
    out = {"type": "拘留", "detention_days": 25, "fine": 0,
           "multi_violation": True,
           "executed_penalty": {"detention_days": 25, "fine": 0},
           "articles": [{"text": "第七十条", "edition": "2012修正"}]}
    assert ("penalty_caps", "error") in _sev(check_penalty_caps(_ctx(out)))


def test_caps_merged_within_art16():
    out = {"type": "拘留并处罚款", "detention_days": 20, "fine": 5000,
           "multi_violation": True,
           "executed_penalty": {"detention_days": 20, "fine": 5000},
           "articles": [{"text": "第七十条", "edition": "2012修正"}]}
    assert not check_penalty_caps(_ctx(out))


def test_caps_2025_hard_after_caps_table():
    out = {"type": "罚款", "detention_days": 0, "fine": 6000,
           "multi_violation": False,
           "articles": [{"text": "第八十二条", "edition": "2025修订"}]}
    assert ("penalty_caps", "error") in _sev(check_penalty_caps(_ctx(out)))
    ok = {"type": "罚款", "detention_days": 0, "fine": 4500,
          "multi_violation": False,
          "articles": [{"text": "第八十二条", "edition": "2025修订"}]}
    assert not [f for f in check_penalty_caps(_ctx(ok)) if f.severity == "error"]


# ---------- 条号-版本绑定 ----------

def test_article_edition_binding():
    bad = _ctx({"type": "罚款", "detention_days": 0, "fine": 500,
                "articles": [{"text": "治安管理处罚法第八十二条", "edition": "2012修正"}]})
    assert any(f.check == "article_edition" and f.severity == "error"
               for f in check_article_edition(bad))
    good = _ctx({"type": "罚款", "detention_days": 0, "fine": 500,
                 "articles": [{"text": "治安管理处罚法第七十条", "edition": "2012修正"}]})
    assert check_article_edition(good) == []


# ---------- 类型一致性 ----------

def test_outcome_matrix():
    assert not check_outcome_consistency(_ctx({"type": "拘留并处罚款", "detention_days": 5, "fine": 500}))
    assert check_outcome_consistency(_ctx({"type": "拘留", "detention_days": 0, "fine": 0}))
    assert check_outcome_consistency(_ctx({"type": "罚款", "detention_days": 5, "fine": 500}))
    assert check_outcome_consistency(_ctx({"type": "不予处罚", "detention_days": 3, "fine": 0}))


# ---------- 日期顺序（模型值 + 信封交叉） ----------

def test_dates_order():
    f = check_dates(_ctx(dates={"behavior": "2023-06-01", "decision": "2023-06-02"},
                         rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                              "behavior_date": "2023-06", "decision_date": "2023-06"}))
    assert not any(x.severity == "error" for x in f)
    f = check_dates(_ctx(dates={"behavior": "2023-08-01", "decision": "2023-06-02"},
                         rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                              "behavior_date": "2023-08", "decision_date": "2023-06"}))
    assert ("dates_order", "error") in _sev(f)
    f = check_dates(_ctx(dates={"behavior": "2023-08-01", "decision": None},
                         rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                              "behavior_date": "2023-08", "decision_date": "2023-06"}))
    assert ("dates_order", "warn") in _sev(f)
    assert ("dates_order", "error") not in _sev(f)


def test_dates_model_vs_envelope_cross():
    f = check_dates(_ctx(dates={"behavior": "2023-09-01", "decision": "2023-09-02"},
                         rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                              "behavior_date": "2023-05", "decision_date": "2023-09"}))
    assert ("dates_order", "warn") in _sev(f)   # 模型行为月 ≠ 信封


# ---------- subject（三档） ----------

def test_subject_three_tiers():
    cleaned = "经查，张某某在某棋牌室赌博。决定给予行政拘留五日。"
    spans = {"facts": [(0, 13, 0, 13)]}
    assert check_subject(_ctx(subject={"mention": "张某某"}, spans=spans, cleaned=cleaned)) == []
    f = check_subject(_ctx(subject={"mention": "李某某"}, spans=[], cleaned=cleaned))
    assert ("subject", "error") in _sev(f)


# ---------- decision 区间存在 ----------

def test_decision_required_when_outcome_present():
    out = {"type": "拘留", "detention_days": 5, "fine": 0}
    assert check_decision_present(_ctx(outcome=out, spans={})) != []


# ---------- facts 内容质量族（parse_qc 迁移） ----------

def test_fq_conclusion_tail_error():
    cleaned = "张某某在某棋牌室赌博。情节严重。决定给予行政拘留十日。"
    spans = {"facts": [(0, 20, 0, 20)]}   # facts 区间含尾部定性句（snap 未生效的残留）
    f = check_facts_quality(_ctx(spans=spans, cleaned=cleaned))
    assert any(x.severity == "error" and "定性句收尾" in x.detail for x in f)


def test_fq_conclusion_mid_warn():
    cleaned = "张某某在某棋牌室赌博，情节严重，赌资五千元。后被查获。"
    spans = {"facts": [(0, 28, 0, 28)]}
    f = check_facts_quality(_ctx(spans=spans, cleaned=cleaned))
    assert any(x.severity == "warn" and "定性句段中" in x.detail for x in f)


def test_fq_evidence_and_genjv_warn():
    spans = {"facts": [(0, 40, 0, 40)]}
    f1 = check_facts_quality(_ctx(spans=spans, cleaned="张某某赌博。以上事实有询问笔录证实。" + "补充" * 10))
    assert any("证据句混入" in x.detail for x in f1)
    f2 = check_facts_quality(_ctx(spans=spans, cleaned="张某某赌博。根据《治安管理处罚法》其行为发生于某月。" + "补充" * 8))
    assert any("根据法条" in x.detail for x in f2)


def test_fq_empty_error():
    f = check_facts_quality(_ctx(spans={}, cleaned="任意"))
    assert any(x.severity == "error" and "facts 区间缺失" in x.detail for x in f)


# ---------- 全注册表冒烟（v2 区间语义） ----------

def test_run_checks_smoke():
    from cleanse import sentence_table
    from locate import OffsetIndex
    cleaned = ("经查，张某某在某棋牌室赌博。以上事实有询问笔录证实。本机关认为其行为已构成赌博。"
               "根据治安管理处罚法第七十条之规定，决定给予行政拘留五日，罚款一千五百元。")
    sentences = sentence_table(cleaned)
    index = OffsetIndex({"orig_len": len(cleaned), "deletes": [], "subs": []})
    zones = [{"type": "facts", "from": 1, "to": 1},
             {"type": "evidence", "from": 2, "to": 2},
             {"type": "reasoning", "from": 3, "to": 3},
             {"type": "decision", "from": 4, "to": 4}]
    spans = {}
    for z in zones:
        cs = sentences[z["from"] - 1][0]
        ce = sentences[z["to"] - 1][1]
        a, b = index.span(cs, ce)
        spans.setdefault(z["type"], []).append((cs, ce, a, b))
    out = {"zones": zones,
           "subject": {"mention": "张某某", "aliases": []},
           "outcome": {"type": "拘留并处罚款", "detention_days": 10, "fine": 1500,
                       "not_executed": "否", "multi_violation": False,
                       "executed_penalty": {"detention_days": 0, "fine": 0},
                       "confiscation": [], "detention_items": [],
                       "articles": [{"text": "第七十条", "edition": "2012修正"}],
                       "stated_circumstances": []},
           "dates": {"behavior": "2023-05-01", "decision": "2023-05-02"},
           "review": {"result": "无", "changed_outcome": None},
           "gambling": {"verdict": "是", "reason": "赌博"}, "confidence": "high"}
    ctx = _ctx(outcome=out["outcome"], dates=out["dates"], subject=out["subject"],
               zones=zones, sentences=sentences, spans=spans, cleaned=cleaned)
    findings = run_checks(ctx)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors, [f.detail for f in errors]


# ---------- 值-文对账（仔细校验层） ----------

def test_value_grounded_fine_hallucination():
    from s3 import check_value_grounded
    ctx = _ctx(outcome={"type": "罚款", "detention_days": 0, "fine": 9999,
                        "fine_masked": False, "articles": []},
               rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                    "form": "叙述式-独立成篇", "cleaned_text": "张某某在某棋牌室赌博。"})
    f = check_value_grounded(ctx)
    assert any(x.severity == "error" and "9999" in x.detail for x in f)


def test_value_grounded_fine_variants():
    # 正文写中文数字，模型出阿拉伯——变体匹配应有据
    from s3 import check_value_grounded
    ctx = _ctx(outcome={"type": "罚款", "detention_days": 0, "fine": 500,
                        "fine_masked": False, "articles": []},
               rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                    "form": "叙述式-独立成篇", "cleaned_text": "决定罚款五百元。"})
    assert not [x for x in check_value_grounded(ctx) if x.check == "value_grounded"]


def test_value_grounded_fine_masked_skipped():
    from s3 import check_value_grounded
    ctx = _ctx(outcome={"type": "罚款", "detention_days": 0, "fine": 0,
                        "fine_masked": True, "articles": []},
               rec={"prefilter": {"gambling": "是"}, "source_type": "执法公示",
                    "form": "字段表公示", "cleaned_text": "决定罚款＊＊＊＊元。"})
    assert not [x for x in check_value_grounded(ctx) if x.check == "value_grounded"]


def test_value_grounded_article_optional_di_prefix():
    from s3 import check_value_grounded
    rec = {"prefilter": {"gambling": "是"}, "source_type": "执法公示",
           "form": "字段表公示", "cleaned_text": "依据《中华人民共和国治安管理处罚法》七十条处罚。"}
    ctx = _ctx(outcome={"type": "罚款", "detention_days": 0, "fine": 0,
                        "articles": [{"text": "第七十条", "edition": "2012修正"}]}, rec=rec)
    assert not [x for x in check_value_grounded(ctx) if x.severity == "error"]
    rec["cleaned_text"] = "依据《中华人民共和国治安管理处罚法》十条处罚。"
    assert any(x.severity == "error" for x in check_value_grounded(ctx))


def test_value_grounded_article_shorthand_same_article():
    from s3 import check_value_grounded
    rec = {"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
           "form": "叙述式-独立成篇", "cleaned_text": "依照第十一条第一款、第二款、第七十条处罚。"}
    ctx = _ctx(outcome={"type": "罚款", "detention_days": 0, "fine": 0,
                        "articles": [{"text": "第十一条第二款", "edition": "2012修正"}]}, rec=rec)
    assert not [x for x in check_value_grounded(ctx) if x.severity == "error"]
    rec["cleaned_text"] = "依照第十条第一款、第二款、第七十条处罚。"
    assert any(x.severity == "error" for x in check_value_grounded(ctx))


def test_cn_read():
    from s3 import _CN_READ
    assert _CN_READ(3000) == "三千"
    assert _CN_READ(305) == "三百零五"
    assert _CN_READ(15) == "十五"
    assert _CN_READ(10) == "十"
    assert _CN_READ(500) == "五百"


# ---------- 706 湖文本假阳性修复：大写金额"圆整" + 掩码名等价 ----------

def test_value_grounded_fine_cn_upper_yuan():
    # 法宝决定书大写金额惯书"伍佰圆整"——单位类须收"圆"（706 实测 8 件误判幻觉）
    from s3 import check_value_grounded
    ctx = _ctx(outcome={"type": "罚款", "detention_days": 0, "fine": 500,
                        "fine_masked": False, "articles": []},
               rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                    "form": "叙述式-独立成篇",
                    "cleaned_text": "根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对王xx罚款伍佰圆整。"})
    assert not [x for x in check_value_grounded(ctx) if x.check == "value_grounded"]


def test_value_grounded_fine_still_catches_hallucination_with_yuan():
    from s3 import check_value_grounded
    ctx = _ctx(outcome={"type": "罚款", "detention_days": 0, "fine": 500,
                        "fine_masked": False, "articles": []},
               rec={"prefilter": {"gambling": "是"}, "source_type": "处罚决定书",
                    "form": "叙述式-独立成篇", "cleaned_text": "现决定对王xx罚款贰佰圆整。"})
    assert any(x.severity == "error" for x in check_value_grounded(ctx))


def test_mask_helpers():
    from s3 import mask_equal, mask_contains, strip_role_prefix
    assert mask_equal("王*乙", "王x乙")
    assert mask_equal("崔**", "崔xx")
    assert not mask_equal("叶*", "叶XX")          # 掩码字数不同 → 保守拒配
    assert mask_equal("张某谋", "张某某")        # 谋落某的掩码位 → 同变体类（target 提取损坏可救回）
    assert mask_equal("蔡**", "蔡素珍")          # 实名↔掩码变体（不予处罚文书决定段书实名）
    assert not mask_equal("张大明", "张小明")     # 等长同姓但实名位冲突 → 拒配
    assert not mask_equal("曾**", "曾国藩x")      # 长度不同 → 拒配
    assert mask_contains("现决定对侯xx以赌博行政拘留三日", "侯xx")
    # 实名↔掩码变体 + 唯一性护栏
    assert mask_contains("曾红权的赌博违法事实不能成立，现决定不予处罚。", "曾**")
    assert not mask_contains("曾红权与曾国藩共同赌博", "曾**")       # 两个实名变体 → 歧义拒配
    assert mask_contains("现查明胡**在棋牌室赌博", "胡汉杨")         # 唯一掩码变体
    assert not mask_contains("胡**和胡××分别处罚", "胡汉杨")        # 两个掩码变体 → 保守拒配
    # 首字锚定：词中截断的掩码开头窗口不得污染变体集（"×为在"不是姓名变体）
    assert mask_contains("民警当场查获邹×为", "邹**")              # 锚定后唯一变体命中
    assert not mask_contains("×为在现场赌博", "邹**")               # 无锚点字 → 不命中
    # 子串语义与原生 in 同宽（"侯某"命中"侯xx"前两位，如同"张某"命中"张某谋"）；
    # 等值闸仍对字数不同保守拒配
    assert mask_contains("现决定对侯xx以赌博", "侯某")
    assert not mask_equal("侯某", "侯xx")
    assert strip_role_prefix("被处罚人王xx") == "王xx"
    assert strip_role_prefix("违法行为人温某某") == "温某某"
    assert strip_role_prefix("当事人") == "当事人"  # 纯前缀不剥成空


def test_subject_mask_equivalence():
    # 掩码异写与角色前缀不应触发 subject 硬失败；真幻觉仍须 error
    cleaned = "经查，王x乙在某棋牌室赌博。决定罚款伍佰圆整。"
    spans = {"facts": [(0, 13, 0, 13)]}
    assert check_subject(_ctx(subject={"mention": "王*乙"}, spans=spans, cleaned=cleaned)) == []
    assert check_subject(_ctx(subject={"mention": "被处罚人王x乙"}, spans=spans, cleaned=cleaned)) == []
    f = check_subject(_ctx(subject={"mention": "魏凤权"}, spans=spans, cleaned=cleaned))
    assert ("subject", "error") in _sev(f)
    # 实名 mention vs 掩码正文（不予处罚文书形态）：变体绑定应通过
    cleaned2 = "经查，蔡**在某棋牌室赌博。违法事实不能成立，决定不予处罚。"
    spans2 = {"facts": [(0, 14, 0, 14)]}
    assert check_subject(_ctx(subject={"mention": "蔡素珍"}, spans=spans2, cleaned=cleaned2)) == []

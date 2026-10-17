"""数据记录契约（records.py）：合格样例无 error；每类问题都能被抓到。"""
import copy
import hashlib

import pytest

from app.discretion import records as R

FULL = ("宜州区公安局行政处罚决定书。违法行为人甲，男。现查明：2025年11月甲在家中参与赌博，"
        "现场查获赌资3000元。以上事实有询问笔录为证。现决定给予甲行政拘留五日的处罚。")
FACTS = "2025年11月甲在家中参与赌博，现场查获赌资3000元。"
DECISION = "现决定给予甲行政拘留五日的处罚。"


def _span(seg: str) -> list[int]:
    i = FULL.index(seg)
    return [i, i + len(seg)]


def delivery() -> dict:
    return {
        "id": "W-000001", "event_id": "E-1", "linked_ids": [], "subject_alias": "甲",
        "source_type": "处罚决定书", "doc_no_hash": "abcd1234abcd1234", "harvest_date": "2026-10-16",
        "deidentified": "是", "r6_scan": {"passed": True, "date": "2026-10-16"},
        "behavior_date": "2025-11-03", "decision_date": "2025-11-04", "authority": "某县公安局",
        "region": "451203", "province": "广西壮族自治区", "law_version": "旧法",
        "text_full": FULL, "text_sha256": hashlib.sha256(FULL.encode("utf-8")).hexdigest(),
        "segmented": True,
        "segments": {"text_facts": _span(FACTS), "text_evidence": None, "text_reasoning": None,
                     "text_decision": _span(DECISION), "text_review": None},
        "text_facts": FACTS, "text_evidence": "", "text_reasoning": "", "text_decision": DECISION, "text_review": "",
        "outcome": {"type": "拘留", "detention_days": 5, "fine": 0, "detention_not_executed": "否",
                    "confiscation": "", "articles": ["治安管理处罚法（2012修正）第七十条"],
                    "stated_circumstances": [], "law_version": "旧法"},
        "review": {"result": "无", "changed_outcome": None},
        "schema_version": "1.0.0", "pipeline_version": "harvest-0.4",
        "quality": {"completeness": {"has_amount": True, "has_outcome": True}, "parse_warnings": [],
                    "ocr": False, "facts_contains_conclusion": False},
    }


def parsed() -> dict:
    d = delivery()
    for k in ("event_id", "linked_ids", "subject_alias", "r6_scan", "text_sha256", "schema_version",
              "pipeline_version", "segments", "doc_no_hash", "deidentified"):
        d.pop(k)
    d.update({"record_version": R.RECORD_VERSION, "source": "公开网页", "batch": "20261015-weekly",
              "parser": "harvest/parse.py@0.4", "source_ref": "https://example.gov.cn/a.html",
              "doc_no": "宜公（治）行罚决字〔2025〕1号", "subject_mention": "王某某", "event_key": "某县公安局|2025-11|3000",
              "extra": {"page_id": "P1"}})
    d["quality"].update({"tier": "L1-金标候选", "in_scope": True, "gambling": "是"})
    return d


def errors(issues):
    return {i.code for i in issues if i.level == "error"}


PARTY = "违法行为人甲，男。"


def test_party_segment_is_optional_and_checked():
    d = delivery()
    d["text_party"], d["segments"]["text_party"] = PARTY, _span(PARTY)
    assert errors(R.check_delivery(d)) == set()
    d["segments"]["text_party"] = [0, 3]
    assert "segment_offset_mismatch" in errors(R.check_delivery(d))
    p = parsed()
    p["text_party"] = "不在正文里的当事人段"
    assert "segment_not_substring" in errors(R.check_parsed(p))


def test_party_segment_must_precede_facts():
    p = parsed()
    p["text_party"] = FACTS
    assert "party_overlaps_facts" in {i.code for i in R.check_parsed(p)}


@pytest.mark.parametrize("otype, days, fine, masked, code", [
    ("罚款", 0, 0, True, None),                            # 源文"罚款**元"：放行，只记警告
    ("拘留并处罚款", 5, 0, True, None),
    ("罚款", 0, 0, False, "outcome_inconsistent"),         # 未标打码仍判错
    ("拘留并处罚款", 0, 0, True, "outcome_inconsistent"),  # 打码只免罚款，拘留天数仍须一致
])
def test_masked_fine(otype, days, fine, masked, code):
    d = delivery()
    d["outcome"].update({"type": otype, "detention_days": days, "fine": fine})
    if masked:
        d["outcome"]["fine_masked"] = True
    issues = R.check_delivery(d)
    assert (code in errors(issues)) if code else not errors(issues)
    if masked and not code:
        assert "fine_masked" in {i.code for i in issues}


def test_valid_records_have_no_errors():
    assert errors(R.check_delivery(delivery())) == set()
    assert errors(R.check_parsed(parsed())) == set()


@pytest.mark.parametrize("mutate, code", [
    (lambda r: r.pop("region"), "missing_field"),
    (lambda r: r.update(law_version=""), "empty_required"),
    (lambda r: r["review"].update(result="驳回"), "bad_enum"),
    (lambda r: r.update(text_sha256="0" * 64), "sha_mismatch"),
    (lambda r: r["segments"].update(text_facts=[0, 5]), "segment_offset_mismatch"),
    (lambda r: r.update(deidentified=False), "not_deidentified"),
    (lambda r: r.update(r6_scan={"passed": False}), "r6_not_passed"),
    (lambda r: r.update(doc_no="宜公〔2025〕1号"), "internal_field_leaked"),
    (lambda r: r["outcome"].update(fine=200), "outcome_inconsistent"),
    (lambda r: r["outcome"].update(type="拘留并处罚款", fine=4000), "fine_over_limit"),
    (lambda r: r["outcome"].update(detention_days=21), "detention_over_limit"),
    (lambda r: r.update(behavior_date="2026-02-01"), "law_version_conflict"),
    (lambda r: r["outcome"].update(law_version="新法"), "law_version_mismatch"),
    (lambda r: r.update(subject_alias="乙"), "bad_alias"),
])
def test_delivery_problems_are_caught(mutate, code):
    r = delivery()
    mutate(r)
    assert code in errors(R.check_delivery(r))


def _with_text(full: str, facts: str) -> dict:
    r = delivery()
    r.update(text_full=full, text_facts=facts, text_sha256=hashlib.sha256(full.encode("utf-8")).hexdigest())
    i = full.index(facts)
    r["segments"]["text_facts"] = [i, i + len(facts)]
    r["segments"]["text_decision"] = None
    r["text_decision"] = ""
    return r


def test_subject_must_appear_in_facts():
    assert "subject_not_in_facts" in errors(R.check_delivery(_with_text("经查：某人参与赌博。", "某人参与赌博。")))


def test_conclusion_words_in_facts_unless_flagged():
    r = _with_text("经查：甲参与赌博，情节严重。", "甲参与赌博，情节严重。")
    assert "conclusion_in_facts" in errors(R.check_delivery(r))
    r["quality"]["facts_contains_conclusion"] = True
    assert "conclusion_in_facts" not in errors(R.check_delivery(r))


def test_prior_penalty_wording_is_not_a_conclusion():
    r = _with_text("经查：甲曾因赌博被处以行政拘留五日，又参与赌博。", "甲曾因赌博被处以行政拘留五日，又参与赌博。")
    assert "conclusion_in_facts" not in errors(R.check_delivery(r))


@pytest.mark.parametrize("leak", ["身份证号码110101199001011234", "联系电话13812345678", "详见 http://x.gov.cn"])
def test_privacy_residue_is_caught(leak):
    r = _with_text(f"经查：甲参与赌博。{leak}", "甲参与赌博。")
    assert "privacy_hit" in errors(R.check_delivery(r))


def test_merged_detention_is_only_a_warning():
    r = delivery()
    r["outcome"]["detention_days"] = 18
    issues = R.check_delivery(r)
    assert "detention_over_limit" not in errors(issues)
    assert any(i.code == "detention_merged" for i in issues)


def test_parsed_layer_checks():
    r = parsed()
    r["text_facts"] = "不在正文里的事实"
    assert "segment_not_substring" in errors(R.check_parsed(r))
    r = parsed()
    r["site"] = "x.gov.cn"
    assert any(i.code == "unknown_field" and i.level == "warn" for i in R.check_parsed(r))
    r = parsed()
    r["quality"]["tier"] = "L1"
    r["text_facts"] = ""
    assert "tier_inconsistent" in errors(R.check_parsed(r))
    r = parsed()
    r.pop("batch")
    assert "missing_field" in errors(R.check_parsed(r))


def test_only_month_precision_is_info_not_error():
    r = delivery()
    r["behavior_date"] = "2025-11"
    issues = R.check_delivery(r)
    assert not errors(issues) and any(i.code == "date_month_only" for i in issues)


def test_statutory_limits_come_from_norm_library():
    lim = R.statutory_limits()
    assert lim["旧法"][:2] == (15, 3000) and lim["新法"][:2] == (15, 5000) and lim["新法"][2] == 20


def test_field_table_covers_every_field():
    table = R.field_table_markdown()
    for f in R.FIELDS + R.OUTCOME_FIELDS + R.QUALITY_FIELDS:
        assert f"`" in table and f.name in table
    assert copy.deepcopy(delivery())["id"] == "W-000001"


def test_data_spec_table_is_in_sync_with_code():
    from pathlib import Path
    spec = Path(__file__).resolve().parents[3] / "docs" / "05-research" / "data-spec.md"
    assert R.field_table_markdown() in spec.read_text("utf-8"), \
        "字段总表与代码不一致：运行 python -m app.discretion.records update-doc ../docs/05-research/data-spec.md"

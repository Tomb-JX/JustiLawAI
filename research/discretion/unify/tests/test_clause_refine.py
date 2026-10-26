from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleanse import sentence_table  # noqa: E402
from fact_spans import effective_fact_spans  # noqa: E402
from run_seg import request_for, validated_output  # noqa: E402
from s3 import check_facts_quality, run_checks  # noqa: E402
from fact_spans import fact_view, candidate_fact_clauses  # noqa: E402
from fact_spans import fact_zone_conflicts  # noqa: E402
from run_elements import build_inputs  # noqa: E402
from locate import OffsetIndex  # noqa: E402
import hashlib


def _case():
    text = "现查明：张某在某棋牌室参与赌博，其行为已构成赌博。"
    rec = {"cleaned_text": text, "sentences": sentence_table(text), "form": "叙述式-独立成篇",
           "source_type": "处罚决定书", "prefilter": {"gambling": "是"}}
    output = {"zones": [{"type": "facts", "from": 1, "to": 1}],
              "subject": {"mention": "张某", "aliases": []},
              "outcome": {"type": "罚款", "detention_days": 0, "fine": 500},
              "dates": {"behavior": None, "decision": None},
              "review": {"result": "无", "changed_outcome": None},
              "gambling": {"verdict": "是", "reason": "原文载明"}, "confidence": "high"}
    return rec, output


def test_clause_refine_request_and_effective_facts():
    rec, output = _case()
    prompt = request_for(rec, clause_refine=True)
    assert "[C" in prompt[1]["content"] and "fact_clause_ids" in prompt[0]["content"]
    output["fact_clause_ids"] = [2]
    output["fact_clause_roles"] = {"2": "behavior_core"}
    checked = validated_output(output, rec, clause_refine=True)
    effective = effective_fact_spans(rec, checked)
    assert "构成赌博" not in "".join(rec["cleaned_text"][a:b] for a, b, *_ in effective)
    findings = check_facts_quality({"record": rec, "output": checked,
                                    "spans": {"facts": [(0, len(rec["cleaned_text"]), 0, len(rec["cleaned_text"]))]}})
    assert not [f for f in findings if f.severity == "error"]


def test_clause_refine_rejects_unknown_or_missing_ids():
    rec, output = _case()
    for ids in (None, [999]):
        if ids is not None:
            output["fact_clause_ids"] = ids
            output["fact_clause_roles"] = {str(i): "behavior_core" for i in ids}
        try:
            validated_output(output, rec, clause_refine=True)
        except ValueError:
            continue
        raise AssertionError("invalid fact clause IDs accepted")


def test_s3_reports_invalid_clause_refs_without_crashing():
    rec, output = _case()
    output["fact_clause_ids"] = [999]
    ctx = {"record": rec, "output": output, "sentences": rec["sentences"],
           "spans": {"facts": [(0, len(rec["cleaned_text"]), 0, len(rec["cleaned_text"]))]}}
    findings = run_checks(ctx)
    assert any(f.check == "schema" and f.severity == "error" and "fact_clause_ids" in f.detail
               for f in findings)


def test_refined_fact_view_is_shared_by_s3_and_element_input():
    text = "现查明：2025年1月1日，张某参与赌博，其行为已构成赌博。"
    rec = {"cleaned_text": text, "sentences": sentence_table(text), "form": "叙述式-独立成篇",
           "source_type": "处罚决定书", "subject_mention": "张某", "_text_full": text,
           "text_orig_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "prefilter": {"gambling": "是"}}
    clauses = candidate_fact_clauses(text, rec["sentences"])
    behavior = next(c["id"] for c in clauses if "张某参与赌博" in c["text"])
    out = {"zones": [{"type": "facts", "from": 1, "to": 1}], "fact_clause_ids": [behavior]}
    view = fact_view(rec, out)
    projected = "".join(v["text"] for v in view)
    assert "2025年1月1日" in projected and "张某参与赌博" in projected
    assert "现查明" not in projected and "构成赌博" not in projected
    assert [v["role"] for v in view] == ["context_time", "narrative_fact"]
    inp = build_inputs(rec, out, OffsetIndex({"orig_len": len(text), "deletes": []}))
    assert "2025年1月1日" in inp["facts_text"]
    assert next(v["normalized_time"]["start_date"] for v in inp["sentence_view"]
                if v.get("fact_role") == "context_time") == "2025-01-01"
    assert "现查明" not in inp["facts_text"] and "构成赌博" not in inp["facts_text"]
    findings = check_facts_quality({"record": rec, "output": out, "spans": {"facts": [(0, len(text), 0, len(text))]}})
    assert not [f for f in findings if f.severity == "error" or "定性" in f.detail]


def test_clause_selection_survives_sentence_zone_conflict():
    text = "现查明2025年10月1日，张某参与赌博，其行为构成赌博。"
    rec = {"cleaned_text": text, "sentences": sentence_table(text), "subject_mention": "张某",
           "_text_full": text, "text_orig_sha256": hashlib.sha256(text.encode()).hexdigest()}
    clauses = candidate_fact_clauses(text, rec["sentences"])
    date = next(c["id"] for c in clauses if "现查明2025" in c["text"])
    behavior = next(c["id"] for c in clauses if "张某参与赌博" in c["text"])
    out = {"zones": [{"type": "reasoning", "from": 1, "to": 1}],
           "fact_clause_ids": [date, behavior],
           "fact_clause_roles": {str(date): "context_time", str(behavior): "behavior_core"}}
    assert fact_zone_conflicts(rec, out) == [date, behavior]
    view = fact_view(rec, out)
    assert "现查明" not in "".join(v["text"] for v in view)
    inp = build_inputs(rec, out, OffsetIndex({"orig_len": len(text), "deletes": []}))
    assert "张某参与赌博" in inp["facts_text"] and "构成赌博" not in inp["facts_text"]


def test_pure_legal_conclusion_yields_no_fact_view():
    text = "综上所述，张某的行为已经构成赌博，根据治安管理处罚法第七十条，现决定罚款。"
    rec = {"cleaned_text": text, "sentences": sentence_table(text)}
    out = {"zones": [{"type": "reasoning", "from": 1, "to": 1}],
           "fact_clause_ids": [], "fact_clause_roles": {}}
    assert candidate_fact_clauses(text, rec["sentences"])
    assert fact_view(rec, out) == []


def test_role_contract_rejects_heading_and_date_as_behavior():
    text = "现查明：2025年1月1日，张某参与赌博，其行为构成赌博。"
    rec = {"cleaned_text": text, "sentences": sentence_table(text)}
    clauses = candidate_fact_clauses(text, rec["sentences"])
    heading, date = clauses[0]["id"], clauses[1]["id"]
    for cid in (heading, date):
        out = {"zones": [{"type": "facts", "from": 1, "to": 1}],
               "fact_clause_ids": [cid], "fact_clause_roles": {str(cid): "behavior_core"}}
        try:
            fact_view(rec, out)
        except ValueError:
            continue
        raise AssertionError("invalid role accepted")

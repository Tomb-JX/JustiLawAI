from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleanse import sentence_table  # noqa: E402
from fact_spans import effective_fact_spans  # noqa: E402
from run_seg import request_for, validated_output  # noqa: E402
from s3 import check_facts_quality, run_checks  # noqa: E402


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
    output["fact_clause_ids"] = [1, 2]
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

"""Tests for evidence_contract.py — evidence semantics validation."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence_contract import EvidenceValidator, EvidenceIssue  # noqa: E402

V = EvidenceValidator()


def _record(evidence_fields: dict | None = None, *, text_full: str = "甲收台费十元。",
            facts_text: str = "甲收台费十元。", meta_text: str = "") -> dict:
    """Build a minimal record for testing."""
    elements = {}
    for group in ("conduct", "amounts", "persons", "venue", "intent", "circumstances", "person"):
        elements[group] = {}
    if evidence_fields:
        for path, item in evidence_fields.items():
            g, f = path.split(".")
            elements[g][f] = item
    return {"id": "T-1", "input": {"target": "甲", "text_full": text_full,
            "facts_text": facts_text, "meta_text": meta_text,
            "text_orig_sha256": hashlib.sha256(text_full.encode()).hexdigest()},
            "elements": elements}


def test_absent_field_ok():
    r = _record({"amounts.commission": {"status": "未提及", "value": None, "evidence": []}})
    assert V.validate_record(r) == []


def test_absent_with_value_fails():
    r = _record({"amounts.commission": {"status": "未提及", "value": 10, "evidence": []}})
    issues = V.validate_record(r)
    assert any(i.code == "absent_with_value" for i in issues)


def test_absent_with_evidence_fails():
    r = _record({"amounts.commission": {"status": "未提及", "value": None,
                 "evidence": [{"quote": "十元", "start": 3, "end": 5}]}})
    issues = V.validate_record(r)
    assert any(i.code == "absent_with_evidence" for i in issues)


def test_present_without_evidence_fails():
    r = _record({"amounts.commission": {"status": "明确", "value": 10, "evidence": []}})
    issues = V.validate_record(r)
    assert any(i.code == "present_without_evidence" for i in issues)


def test_quote_not_in_text_fails():
    r = _record({"amounts.commission": {"status": "明确", "value": 10,
                 "evidence": [{"quote": "不存在的引文", "start": 0, "end": 5}]}})
    issues = V.validate_record(r)
    assert any(i.code == "quote_not_in_text" for i in issues)


def test_quote_forbidden_source():
    """Quote in text_full but not in facts_text or meta_text → warning."""
    r = _record(
        {"amounts.commission": {"status": "明确", "value": 10,
         "evidence": [{"quote": "台费", "start": 2, "end": 4}]}},
        text_full="甲收台费十元。", facts_text="", meta_text="")
    issues = V.validate_record(r)
    assert any(i.code == "quote_forbidden_source" for i in issues)


def test_offset_mismatch_fails():
    r = _record({"amounts.commission": {"status": "明确", "value": 10,
                 "evidence": [{"quote": "收台费十元", "start": 0, "end": 5}]}})
    issues = V.validate_record(r)
    assert any(i.code == "offset_mismatch" for i in issues)


def test_valid_evidence_passes():
    r = _record({"amounts.commission": {"status": "明确", "value": {"min": 10, "max": 10},
                 "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}})
    assert V.validate_record(r) == []


def test_batch_validation():
    r1 = _record({"amounts.commission": {"status": "明确", "value": {"min": 10, "max": 10},
                   "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}})
    r2 = _record({"amounts.commission": {"status": "未提及", "value": 10, "evidence": []}})
    r2["id"] = "T-2"
    report = V.validate_batch([r1, r2])
    assert report["total"] == 2
    assert report["passed"] == 1
    assert report["failed"] == 1
    assert "absent_with_value" in report["issue_counts"]
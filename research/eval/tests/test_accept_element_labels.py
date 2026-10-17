import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from accept_element_labels import FIELD_INFO, evaluate  # noqa: E402


def row(i):
    full = "甲收台费十元。"
    elements = {}
    for path in FIELD_INFO:
        group, name = path.split(".")
        elements.setdefault(group, {})[name] = {"status": "未提及", "value": None, "evidence": []}
    return {"id": f"T-{i}", "input": {"target": "甲", "facts_text": full,
            "meta_text": "", "text_full": full,
            "text_orig_sha256": hashlib.sha256(full.encode()).hexdigest()},
            "elements": elements, "element_schema_version": "1.1.0",
            "element_prompt_version": "element-v1",
            "label_provenance": "model-adjudicated", "human_review": False}


def test_pilot_requires_arbitration_and_original_hash():
    rows = [row(i) for i in range(200)]
    assert evaluate(rows)["pilot_pass"] is False
    report = evaluate(rows, rows, rows)
    assert report["pilot_pass"] is False  # 全空标签没有证据，不可放行
    rows[0]["input"]["text_orig_sha256"] = "0" * 64
    report = evaluate(rows, rows, rows)
    assert report["schema_valid_rate"] < 1
    assert report["issue_counts"]["text_hash_mismatch"] == 1


def test_quote_offset_and_provenance():
    r = row(1)
    r["elements"]["amounts"]["commission"] = {
        "status": "明确", "value": {"min": 10, "max": 10},
        "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}
    report = evaluate([r])
    assert report["evidence_hit_rate"] == 1
    assert report["numeric_consistency_rate"] is None  # 中文数额不做伪机械换算
    r["human_review"] = True
    assert evaluate([r])["issue_counts"]["bad_provenance"] == 1


def test_synthetic_pilot_gate_passes_without_accuracy_claim():
    rows = [row(i) for i in range(200)]
    for r in rows:
        r["elements"]["amounts"]["commission"] = {
            "status": "明确", "value": {"min": 10, "max": 10},
            "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}
    report = evaluate(rows, rows, rows)
    assert report["pilot_pass"] is True
    assert report["evidence_hit_rate"] == 1
    assert report["model_adjudicated_not_human_gold"] is True
    assert "field_accuracy" not in report

import copy
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from accept_element_labels import (FIELD_INFO, SCHEMA_VERSION, classify_divergences,  # noqa: E402
                                    compare_predictions, evaluate)


def row(i):
    full = "甲收台费十元。"
    elements = {}
    for path in FIELD_INFO:
        group, name = path.split(".")
        elements.setdefault(group, {})[name] = {"status": "未提及", "value": None, "evidence": []}
    return {"id": f"T-{i}", "input": {"target": "甲", "facts_text": full,
            "meta_text": "", "text_full": full,
            "text_orig_sha256": hashlib.sha256(full.encode()).hexdigest()},
            "elements": elements, "element_schema_version": SCHEMA_VERSION,
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


# --- E-06 tests ---


def test_smoke_pass_criteria():
    """≤12 records with structural validity and evidence hit ≥95% should pass smoke."""
    rows = [row(i) for i in range(12)]
    for r in rows:
        r["elements"]["amounts"]["commission"] = {
            "status": "明确", "value": {"min": 10, "max": 10},
            "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}
    report = evaluate(rows)
    assert report["smoke_pass"] is True
    assert report["spec_pass"] is False  # ≤12 is smoke, not spec


def test_spec_pass_criteria():
    """13-36 records with structural validity, evidence hit ≥95%, and no prompt revision."""
    rows = [row(i) for i in range(20)]
    for r in rows:
        r["elements"]["amounts"]["commission"] = {
            "status": "明确", "value": {"min": 10, "max": 10},
            "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}
    report = evaluate(rows, rows, rows)
    assert report["spec_pass"] is True
    assert report["smoke_pass"] is False  # 20 is > 12


def test_divergence_classification_status_only():
    """Same value, different status should be classified as status_only."""
    a = {"T-1": {"amounts.commission": {"status": "明确", "value": {"min": 10, "max": 10}}}}
    b = {"T-1": {"amounts.commission": {"status": "推断", "value": {"min": 10, "max": 10}}}}
    result = classify_divergences(a, b)
    assert result["amounts.commission"]["status_only"] == 1
    assert result["amounts.commission"]["value"] == 0


def test_divergence_classification_value():
    """Different values should be classified as value divergence."""
    a = {"T-1": {"conduct.behavior_type": {"status": "明确", "value": "参与赌博"}}}
    b = {"T-1": {"conduct.behavior_type": {"status": "明确", "value": "为赌博提供条件"}}}
    result = classify_divergences(a, b)
    assert result["conduct.behavior_type"]["value"] == 1
    assert result["conduct.behavior_type"]["status_only"] == 0


def test_divergence_classification_absent_vs_present():
    """One absent, one present should be absent_vs_present."""
    a = {"T-1": {"venue.venue_type": {"status": "未提及", "value": None}}}
    b = {"T-1": {"venue.venue_type": {"status": "明确", "value": "住宅"}}}
    result = classify_divergences(a, b)
    assert result["venue.venue_type"]["absent_vs_present"] == 1


def test_divergence_types_in_arbitration():
    """E-06 divergence types should appear in arbitration report."""
    rows = [row(i) for i in range(200)]
    # Create A and B with a status_only divergence on conduct.role
    a_rows = copy.deepcopy(rows)
    b_rows = copy.deepcopy(rows)
    for r in a_rows:
        r["elements"]["conduct"]["role"] = {"status": "明确", "value": "参赌者",
                                             "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}
    for r in b_rows:
        r["elements"]["conduct"]["role"] = {"status": "推断", "value": "参赌者",
                                             "evidence": [{"quote": "收台费十元", "start": 1, "end": 6}]}
    report = evaluate(rows, a_rows, b_rows)
    assert "divergence_types" in report["arbitration"]
    assert report["arbitration"]["divergence_types"]["status_only"] > 0


def test_compare_predictions():
    """compare_predictions should compute precision/recall for key fields."""
    # Reference: behavior_type = 参与赌博
    ref = {}
    for i in range(10):
        fields = {}
        for path in FIELD_INFO:
            group, name = path.split(".")
            fields[path] = {"status": "未提及", "value": None}
        fields["conduct.behavior_type"] = {"status": "明确", "value": "参与赌博"}
        ref[f"T-{i}"] = fields
    # Predictions: 8 correct, 2 wrong
    pred = copy.deepcopy(ref)
    pred["T-8"]["conduct.behavior_type"] = {"status": "明确", "value": "为赌博提供条件"}
    pred["T-9"]["conduct.behavior_type"] = {"status": "未提及", "value": None}
    result = compare_predictions(pred, ref)
    assert result["records_common"] == 10
    bt = result["fields"]["conduct.behavior_type"]
    assert bt["ref_present"] == 10
    assert bt["pred_present"] == 9  # T-9 absent
    assert bt["values_match"] == 8
    assert bt["recall"] == 0.8
    assert result["summary"]["key_fields_mean_recall"] is not None

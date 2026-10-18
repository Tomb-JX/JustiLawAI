"""Tests for m1_efficiency_audit.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from m1_efficiency_audit import audit  # noqa: E402


def _mock_probe(n: int = 10) -> dict:
    """Build a minimal mock M1 probe JSON."""
    records = []
    for i in range(n):
        records.append({
            "id": f"P-{i}", "ok": True, "raw_json_valid": True, "raw_items": 6,
            "valued_fields": 4, "valued_by_field": {"conduct.behavior_type": 1, "conduct.role": 1,
                                                     "conduct.method": 1, "venue.venue_type": 1},
            "evidence_by_field": {"conduct.behavior_type": 1, "conduct.role": 1,
                                  "conduct.method": 1, "venue.venue_type": 1},
            "evidence_quotes": 4, "evidence_outside_allowed_view": 0,
            "dropped": {"取值无法解析": 2}, "dropped_by_field_reason": {
                "conduct.times|取值无法解析": 1, "person.age|取值无法解析": 1},
            "seconds": 5.0 + i * 0.5, "eval_tokens": 200 + i * 10,
        })
    return {"slice": "mock", "model": "test-model", "sample_method": "mock",
            "records": records, "summary": {"completed": n, "failed": 0}}


def test_audit_basic_structure():
    report = audit(_mock_probe(10))
    assert report["sample_n"] == 10
    assert report["latency"]["records_with_timing"] == 10
    assert report["tokens"]["total_tokens"] > 0
    assert report["throughput"]["records_per_second"] > 0
    assert "bottlenecks" in report


def test_audit_scaling_estimate():
    report = audit(_mock_probe(10), scale_to=1000)
    assert report["scaling_estimate"] is not None
    assert report["scaling_estimate"]["target_records"] == 1000
    assert report["scaling_estimate"]["estimated_total_hours"] > 0


def test_audit_field_efficiency():
    report = audit(_mock_probe(10))
    assert "conduct.behavior_type" in report["field_extraction_rate"]
    assert report["field_extraction_rate"]["conduct.behavior_type"] == 1.0
    assert "conduct.times" in report["field_efficiency"]
    assert report["field_efficiency"]["conduct.times"]["dropped"] == 10  # 1 per record × 10


def test_audit_empty_records():
    report = audit({"records": [], "summary": {"completed": 0, "failed": 0}})
    assert report["error"] == "no valid records"

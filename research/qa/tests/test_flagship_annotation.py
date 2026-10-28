import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assemble_flagship_candidate import evidence_offsets, standards_ok, API
from app.discretion.schema import SCHEMA_VERSION
from run_flagship_arbitration import validate_decisions
from run_flagship_blind_annotation import validate_fields
from validate_annotations import FIELD_TYPES


def empty_fields():
    return {key: {"status": "未提及", "value": None, "evidence": []}
            for key in FIELD_TYPES}


class FlagshipAnnotationTests(unittest.TestCase):
    def test_evidence_and_full_coverage(self):
        fields = empty_fields()
        fields["conduct.method"] = {"status": "明确", "value": "麻将", "evidence": ["打麻将"]}
        self.assertEqual(validate_fields({"fields": fields}, "甲", "甲打麻将"), fields)
        self.assertEqual(evidence_offsets("打麻将", "甲", "甲打麻将", 3), (4, 7))

    def test_open_upper_amount_accepted(self):
        fields = empty_fields()
        fields["amounts.personal_stake"] = {
            "status": "明确", "value": {"min": 10000, "max": None},
            "evidence": ["赌资万元以上"]}
        self.assertEqual(validate_fields({"fields": fields}, "甲", "甲赌资万元以上"), fields)

    def test_adopt_b_copies_b_field(self):
        a = empty_fields()
        b = empty_fields()
        b["conduct.method"] = {"status": "明确", "value": "麻将", "evidence": ["打麻将"]}
        labels = {"A": a, "B": b, "C": a}
        disputed = {"conduct.method": {role: fields["conduct.method"]
                                       for role, fields in labels.items()}}
        decisions = validate_decisions(
            {"decisions": {"conduct.method": {"adopt": "B", "reason_code": "model_reading"}}},
            disputed, labels, "甲", "甲打麻将")
        self.assertEqual(decisions["conduct.method"]["final"], b["conduct.method"])
        self.assertIsNot(decisions["conduct.method"]["final"], a["conduct.method"])

    def test_standards_approval_required(self):
        self.assertFalse(standards_ok(None, "abc"))

    def test_engine_standard_resolution_is_hash_bound(self):
        row = {"id": "SYN-OPEN", "text_sha256": "b" * 64,
               "text_facts": "甲的赌资为三千元以上。"}
        resolution = {"guide_sha256": "guide-hash", "schema_version": SCHEMA_VERSION,
                    "schema_source_sha256": __import__("hashlib").sha256(
                        (API / "app" / "discretion" / "schema.py").read_bytes()).hexdigest(),
                    "profit_purpose_decision": "engine_schema_1.1.0",
                    "open_amount_decision": "schema_supports_open_bound",
                    "decision_source": "engine_collab_log_2026-10-17",
                    "adopted_by": "engine", "adopted_at": "2026-10-17"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resolution.json"
            path.write_text(json.dumps(resolution), encoding="utf-8")
            self.assertTrue(standards_ok(path, "guide-hash", [row]))
            self.assertFalse(standards_ok(path, "different-guide", [row]))
            resolution["schema_version"] = "1.0.0"
            path.write_text(json.dumps(resolution), encoding="utf-8")
            self.assertFalse(standards_ok(path, "guide-hash", [row]))


if __name__ == "__main__":
    unittest.main()

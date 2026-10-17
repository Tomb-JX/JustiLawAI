import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compile_flagship_review import compile_one
from flagship_client import MODELS, REVIEW_TRIO, endpoint
from run_flagship_review import validate_answer


class FlagshipReviewTests(unittest.TestCase):
    def test_local_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            endpoint("ollama")

    def test_contradictory_pass_rejected(self):
        answer = {"privacy": "pass", "subject": "pass", "facts": "pass",
                  "event": "pass", "issue_codes": ["possible_person_name"],
                  "flag_dispositions": {}}
        with self.assertRaises(ValueError):
            validate_answer(answer, [])

    def test_unanimous_flagship_receipt(self):
        entry = {"id": "SYN-001", "version": "synthetic", "event_id": "E-SYN-001",
                 "text_sha256": "a" * 64}
        reviews = {}
        for provider in REVIEW_TRIO:
            model = MODELS[provider][0]
            reviews[provider] = {"id": entry["id"], "version": entry["version"],
                                 "event_id": entry["event_id"], "text_sha256": entry["text_sha256"],
                                 "provider": provider, "requested_model": model,
                                 "returned_model": model, "response_id": "synthetic-response",
                                 "reviewed_at": "2026-10-16T00:00:00+00:00", "status": "valid_review",
                                 "answer": {"privacy": "pass", "subject": "pass", "facts": "pass",
                                            "event": "pass", "issue_codes": [],
                                            "flag_dispositions": {"second_name_detector_signal": "false_positive"}}}
        receipt, status = compile_one(entry, ["second_name_detector_signal"], reviews)
        self.assertEqual(status, "unanimous_pass")
        self.assertEqual(receipt["review_model_ids"], {p: MODELS[p][0] for p in REVIEW_TRIO})
        reviews["qwen"]["returned_model"] = "qwen3.5:9b"
        receipt, status = compile_one(entry, ["second_name_detector_signal"], reviews)
        self.assertIsNone(receipt)
        self.assertEqual(status, "invalid_or_mismatched_review")


if __name__ == "__main__":
    unittest.main()

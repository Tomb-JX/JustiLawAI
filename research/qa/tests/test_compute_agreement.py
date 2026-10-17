"""Regression checks for the G0.3 union denominator and source coverage."""
import json
import tempfile
import unittest
from pathlib import Path

from research.qa.compute_agreement import KEY_NUMERIC, equal_values, main


class AgreementGateTests(unittest.TestCase):
    def test_open_upper_bounds_match_only_same_open_range(self):
        self.assertTrue(equal_values({"min": 10000, "max": None},
                                     {"min": 10000, "max": None}, "amount"))
        self.assertFalse(equal_values({"min": 10000, "max": None},
                                      {"min": 10000, "max": 19999}, "amount"))

    def test_union_includes_both_valued_and_one_sided(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            a_path, b_path = root / "a.jsonl", root / "b.jsonl"
            records = [{"id": f"T-{n}", "text_full": "synthetic evidence"} for n in range(4)]
            (source / "chunk-01.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

            def judgement(value):
                return {"value": value, "status": "明确" if value is not None else "未提及",
                        "evidence": ["synthetic evidence"] if value is not None else []}

            ann_a = []
            ann_b = []
            categorical = [(True, True), (True, False), (True, None), (None, None)]
            amounts = [(10, 10), (20, 20), (30, None), (None, None)]
            for index, source_row in enumerate(records):
                aa = {"intent.profit_purpose": judgement(categorical[index][0]),
                      "amounts.personal_stake": judgement(
                          {"min": amounts[index][0], "max": amounts[index][0]}
                          if amounts[index][0] is not None else None)}
                bb = {"intent.profit_purpose": judgement(categorical[index][1]),
                      "amounts.personal_stake": judgement(
                          {"min": amounts[index][1], "max": amounts[index][1]}
                          if amounts[index][1] is not None else None)}
                ann_a.append({"id": source_row["id"], "fields": aa})
                ann_b.append({"id": source_row["id"], "fields": bb})
            a_path.write_text("".join(json.dumps(r) + "\n" for r in ann_a), encoding="utf-8")
            b_path.write_text("".join(json.dumps(r) + "\n" for r in ann_b), encoding="utf-8")
            self.assertEqual(main(["agreement", str(a_path), str(b_path), str(source), str(root / "out")]), 0)
            report = json.loads((root / "out/agreement_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["per_field"]["intent.profit_purpose"]["n_union_valued"], 3)
            self.assertEqual(report["per_field"]["amounts.personal_stake"]["n_union_valued"], 3)
            self.assertAlmostEqual(
                report["per_field"]["amounts.personal_stake"]["numeric_exact_rate_union"], 2 / 3)
            self.assertFalse(report["gate_G0_3"]["pass"])  # Other key fields have no positive examples.
            self.assertIn("circumstances.last_prior_penalty_date", KEY_NUMERIC)
            self.assertNotIn("circumstances.violations_last_year", KEY_NUMERIC)


if __name__ == "__main__":
    unittest.main()

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev_slice_first_run import audit, numeric_outcome_audit, text_input  # noqa: E402


def sample():
    source = "被处罚人甲。甲参与赌博。决定对甲罚款100元。"
    meta, facts, decision = "被处罚人甲。", "甲参与赌博。", "决定对甲罚款100元。"
    row = {"id": "A", "event_id": "E", "development_split": "train",
           "source_text": source, "text_orig_sha256": hashlib.sha256(source.encode()).hexdigest(),
           "input": {"target": "甲", "meta_text": meta, "facts_text": facts,
                     "views": [{"type": "meta", "start": 0, "end": len(meta), "text": meta},
                               {"type": "facts", "start": len(meta),
                                "end": len(meta) + len(facts), "text": facts}]},
           "observed_outcome": {"type": "罚款", "detention_days": 0, "fine": 100,
                                "fine_masked": False},
           "observed_outcome_evidence": {"start": len(meta) + len(facts),
                                         "end": len(source), "quote": decision},
           "reference_elements": None, "release_approved": False}
    return row


def test_audit_rejects_overlap_and_hash_drift():
    row = sample()
    manifest = {"records": 1, "events": 1}
    assert audit([row], manifest)["problem_counts"] == {}
    assert text_input(row) == "被处罚人甲。\n甲参与赌博。"
    row["input"]["views"][1]["end"] = len(row["source_text"])
    assert "input_span" in audit([row], manifest)["problem_counts"]
    row = sample()
    row["text_orig_sha256"] = "0" * 64
    assert "original_hash" in audit([row], manifest)["problem_counts"]


def test_audit_handles_bad_offsets_without_crash():
    row = sample()
    row["observed_outcome_evidence"]["start"] = None
    assert "outcome_span" in audit([row], {"records": 1, "events": 1})["problem_counts"]


def test_numeric_audit_reads_uppercase_chinese_amount():
    row = sample()
    row["observed_outcome_evidence"]["quote"] = "对甲行政拘留五日并处罚款人民币叁仟元。"
    row["observed_outcome"].update(type="拘留并处罚款", detention_days=5, fine=3000)
    checked = numeric_outcome_audit([row])
    assert checked["checked"] == {"detention_days": 1, "fine": 1}
    assert checked["mismatch"] == []

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleanse import sentence_table  # noqa: E402
from fact_spans import fact_text, validate_fact_spans  # noqa: E402


def test_mixed_sentence_can_retain_only_verifiable_fact_prefix():
    text = "被查获时潘小慧持有赌资110元，潘小慧的行为已构成赌博。"
    boundary = text.index("，潘小慧的行为")
    spans = [{"sentence": 1, "start": 0, "end": boundary, "text": text[:boundary]}]
    assert validate_fact_spans(text, sentence_table(text), spans) == []
    assert fact_text(text, spans) == "被查获时潘小慧持有赌资110元"


def test_pure_legal_conclusion_must_not_be_fabricated_as_fact():
    text = "综上所述，违法行为人明某的行为构成赌博，根据法律现决定罚款。"
    assert validate_fact_spans(text, sentence_table(text), []) == []
    assert fact_text(text, []) == ""


def test_offsets_cannot_shift_or_escape_sentence():
    text = "甲参与赌博。其行为构成赌博。"
    sentences = sentence_table(text)
    assert validate_fact_spans(text, sentences, [
        {"sentence": 1, "start": 0, "end": 6, "text": "甲参与赌博"}])
    assert validate_fact_spans(text, sentences, [
        {"sentence": 1, "start": 0, "end": 5, "text": "乙参与赌博"}])

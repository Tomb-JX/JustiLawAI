from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleanse import sentence_table  # noqa: E402
from fact_spans import clause_table, fact_text, resolve_fact_clause_ids, validate_fact_spans  # noqa: E402


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


def test_clause_ids_resolve_mixed_sentence_without_model_offsets():
    text = "被查获时潘小慧持有赌资110元，潘小慧的行为已构成赌博。"
    sentences = sentence_table(text)
    clauses = clause_table(text, sentences)
    assert [c["text"] for c in clauses] == ["被查获时潘小慧持有赌资110元，", "潘小慧的行为已构成赌博。"]
    spans = resolve_fact_clause_ids(text, sentences, clauses, [1])
    assert fact_text(text, spans).rstrip("，") == "被查获时潘小慧持有赌资110元"
    assert resolve_fact_clause_ids(text, sentences, clauses, []) == []


def test_clause_ids_reject_unseen_or_reordered_ids():
    text = "甲参与赌博，乙也参与赌博。"
    sentences = sentence_table(text)
    clauses = clause_table(text, sentences)
    for selected in ([2, 1], [1, 1], [3]):
        try:
            resolve_fact_clause_ids(text, sentences, clauses, selected)
        except ValueError:
            continue
        raise AssertionError(f"accepted invalid clause IDs: {selected}")


def test_independent_page_positive_and_negative_boundaries():
    examples = [
        ("现已查明：2025年5月26日12时许，黄某未办理许可证，在公园兜售资料，被民警查获，该行为违反了出版物规定。",
         "现已查明：2025年5月26日12时许，黄某未办理许可证，在公园兜售资料，被民警查获，"),
        ("当事人修改主板程序，增加小程序，废除原有奖励，转换为押分与退分，具有押分性质，其行为属于禁止内容。",
         "当事人修改主板程序，增加小程序，废除原有奖励，转换为押分与退分，具有押分性质，"),
        ("综上所述，违法行为人的行为构成赌博，根据法律现决定罚款。", ""),
        ("某人的行为已经构成殴打他人，其行为属于情节较轻的违法行为。", ""),
    ]
    for text, expected in examples:
        sentences = sentence_table(text)
        clauses = clause_table(text, sentences)
        chosen = [c["id"] for c in clauses if c["end"] <= len(expected)]
        spans = resolve_fact_clause_ids(text, sentences, clauses, chosen)
        assert fact_text(text, spans) == expected

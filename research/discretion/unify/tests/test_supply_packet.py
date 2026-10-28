from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleanse import sentence_table  # noqa: E402
from fact_spans import candidate_fact_clauses, fact_view  # noqa: E402
from supply_packet import audit_elements, build_packet  # noqa: E402
from evidence_graph import build_graph, classify_graph_bindings, _e05_time  # noqa: E402
from evidence_types import SourceSpan  # noqa: E402
from audit_supply_replay import currency_surface_coverage, numeric_coverage  # noqa: E402


def packet_for(text: str, target: str = "乙") -> dict:
    view = {"id": "S1", "sentence_id": 1, "type": "facts", "start": 0,
            "end": len(text), "text": text}
    return build_packet(text, {"target": target, "aliases": [], "sentence_view": [view],
                               "source_sha256": hashlib.sha256(text.encode()).hexdigest()},
                        record_id="R1", case_event_id="E1")


def amount_field(value: int, text: str) -> dict:
    return {"amounts": {"personal_stake": {
        "status": "明确", "value": {"min": value, "max": value},
        "evidence": [{"start": 0, "end": len(text), "quote": text}]}}}


def test_personal_amounts_do_not_cross_subjects():
    text = "甲持有赌资300元，乙持有赌资500元。"
    packet = packet_for(text)
    amounts = [q for q in packet["quantities"] if q["type"] == "amount"]
    assert [(q["raw"], q["actor_status"], q["role_hint"]) for q in amounts] == [
        ("300元", "other", "personal_stake"),
        ("500元", "target", "personal_stake")]
    assert audit_elements(amount_field(300, text), packet)["field_disposition"]["amounts.personal_stake"] == {
        "status": "quarantined", "reason": "explicit_other_subject",
        "candidate_ids": [amounts[0]["candidate_id"]]}
    assert audit_elements(amount_field(500, text), packet)["field_disposition"]["amounts.personal_stake"]["status"] == "candidate_supported"


def test_equipment_count_cannot_be_participant_count():
    text = "甲使用3台赌博机。"
    packet = packet_for(text, "甲")
    count = next(q for q in packet["quantities"] if q["type"] == "count")
    assert count["unit"] == "台" and count["role_hint"] == "equipment_count"
    claim = {"persons": {"participant_count": {"status": "明确", "value": 3,
             "evidence": [{"start": 0, "end": len(text), "quote": text}]}}}
    disposition = audit_elements(claim, packet)["field_disposition"]["persons.participant_count"]
    assert disposition["status"] == "quarantined" and disposition["reason"] == "unit_conflict"


def test_time_range_and_duration_keep_distinct_semantics():
    text = "甲于2025年1月至3月参与赌博，持续三个月。"
    packet = packet_for(text, "甲")
    date = next(q for q in packet["quantities"] if q["type"] == "date")
    duration = next(q for q in packet["quantities"] if q["type"] == "duration")
    assert date["start_date"] == "2025-01-01" and date["end_date"] == "2025-03-31"
    assert duration["days"] == 90
    assert text[date["start"]:date["end"]] == date["raw"]
    assert text[duration["start"]:duration["end"]] == duration["raw"]


def test_joint_and_total_not_silently_attached_to_target():
    text = "甲、乙各出300元，共600元。"
    packet = packet_for(text)
    amounts = [q for q in packet["quantities"] if q["type"] == "amount"]
    assert len(amounts) == 2
    assert amounts[0]["actor_status"] == "joint"
    assert amounts[0]["distribution"] == "each"
    assert amounts[1]["distribution"] == "collective"
    assert audit_elements(amount_field(300, text), packet)["field_disposition"]["amounts.personal_stake"]["status"] == "unverified"
    assert audit_elements(amount_field(600, text), packet)["field_disposition"]["amounts.personal_stake"]["status"] != "candidate_supported"


def test_ordinary_word_does_not_create_other_person_conflict():
    text = "刘**通过自己的微信向覃**转账280元购买号码赌博。"
    packet = packet_for(text, "刘**")
    amount = next(q for q in packet["quantities"] if q["type"] == "amount")
    assert amount["actor_status"] != "other"
    assert audit_elements(amount_field(280, text), packet)["field_disposition"]["amounts.personal_stake"]["status"] != "quarantined"


def test_explicit_negative_quantity_cannot_support_positive_field():
    text = "乙未持有赌资300元。"
    packet = packet_for(text)
    disposition = audit_elements(amount_field(300, text), packet)["field_disposition"]["amounts.personal_stake"]
    assert disposition["status"] == "quarantined" and disposition["reason"] == "explicit_negative_claim"


def test_surface_operator_preserved_alongside_e05_projection():
    text = "乙携带20余元，甲携带超过300元。"
    packet = packet_for(text)
    amounts = [q for q in packet["quantities"] if q["type"] == "amount"]
    assert [(q["operator"], q["lower_inclusive"], q["upper"]) for q in amounts] == [
        (">", False, "29.0"), (">", False, None)]
    ranged = next(q for q in packet_for("乙携带300至500元。")["quantities"] if q["type"] == "amount")
    assert ranged["operator"] == "range" and ranged["lower"] == "300.0" and ranged["upper"] == "500.0"


def test_explicit_age_is_separate_from_birth_date_derivation():
    text = "乙，30岁，出生于1995年11月28日。"
    packet = packet_for(text)
    age = next(q for q in packet["quantities"] if q["type"] == "age")
    assert age["role_hint"] == "age" and age["engine_projection"]["min"] == 30
    assert any(q["type"] == "date" and q["role_hint"] == "birth"
               for q in packet["quantities"])


def test_legacy_graph_does_not_promote_equipment_or_shared_scene():
    text = "甲在场。现场查获3台赌博机和赌资500元。"
    view = {"id": "S1", "type": "facts", "start": 0, "end": len(text), "text": text}
    graph = build_graph(text, [view], "甲")
    classify_graph_bindings(graph)
    counts = [n for n in graph["nodes"] if n["kind"] == "count"]
    assert counts and all(n["binding"] == "needs_review" for n in counts)
    assert all(n["binding"] != "shared_fact" for n in graph["nodes"])


def test_legacy_graph_preserves_calendar_range_end():
    text = "2025年1月至3月"
    ref = SourceSpan.from_text(text, 0, len(text))
    date = _e05_time(text, ref)
    assert date["start_date"] == "2025-01-01" and date["end_date"] == "2025-03-31"


def test_replay_counts_masked_currency_as_uncovered_instead_of_parse_success():
    text = "乙持有赌资300元，另有2***元。"
    counts, misses = currency_surface_coverage(packet_for(text))
    assert counts["yuan_markers"] == 2
    assert counts["covered_by_candidate"] == 1
    assert counts["uncovered_with_mask"] == 1
    assert len(misses) == 1


def test_replay_separates_direct_age_from_birth_date_derivation():
    text = "乙于1995年11月28日出生。"
    packet = packet_for(text)
    age = {"person": {"age": {"status": "推断", "value": 30,
                              "evidence": [{"quote": text, "start": 0, "end": len(text)}]}}}
    found = numeric_coverage(age, packet)
    assert len(found) == 1 and not found[0]["candidate_found"]
    assert any(q["type"] == "date" for q in packet["quantities"])


def test_rejects_view_outside_source_or_modified_quote():
    text = "乙持有赌资500元。"
    inp = {"target": "乙", "sentence_view": [{"id": "S1", "type": "facts", "start": 0,
                                                "end": len(text), "text": "甲持有赌资500元。"}]}
    with pytest.raises(ValueError, match="supply_view_not_source_grounded"):
        build_packet(text, inp, record_id="R1")


def test_v2_recovers_intact_miszoned_fact_but_v1_does_not():
    text = "甲主动投案自首。其行为构成赌博。"
    sentences = sentence_table(text)
    v1 = candidate_fact_clauses(text, sentences)
    v2 = candidate_fact_clauses(text, sentences, version="v2")
    assert not v1 and len(v2) >= 1
    record = {"cleaned_text": text, "sentences": sentences}
    out = {"zones": [{"type": "reasoning", "from": 1, "to": 2}],
           "fact_candidate_version": "v2", "fact_clause_ids": [v2[0]["id"]]}
    result = fact_view(record, out)
    assert [x["text"] for x in result] == ["甲主动投案自首。"]


def _split_views(text: str, cut: int, gap: int, target: str = "乙") -> dict:
    """Two facts views separated by a layout wrap, as the sentence table emits them."""
    views = [{"id": "S1", "sentence_id": 1, "type": "facts", "start": 0, "end": cut, "text": text[:cut]},
             {"id": "S2", "sentence_id": 2, "type": "facts", "start": cut + gap, "end": len(text),
              "text": text[cut + gap:]}]
    return {"target": target, "aliases": [], "sentence_view": views,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest()}


def test_layout_wrap_inside_number_is_joined_only_when_enabled():
    text = "乙赌资100\r\n   0元，甲赌资50元。"
    cut = text.index("\r")
    inp = _split_views(text, cut, len("\r\n   "))
    off = [q for q in build_packet(text, inp, record_id="R1")["quantities"] if q["type"] == "amount"]
    assert [q["raw"] for q in off] == ["0元", "50元"]  # v1 behaviour kept by default
    on = build_packet(text, inp, record_id="R1", layout_wraps=True)
    amounts = [q for q in on["quantities"] if q["type"] == "amount"]
    assert [q["engine_projection"]["min"] for q in amounts] == [1000.0, 50.0]
    first = amounts[0]
    assert text[first["start"]:first["end"]] == first["raw"] == "100\r\n   0元"
    assert len(on["visible_spans"]) == 1 and on["layout_wraps"] is True


def test_layout_wrap_not_joined_without_digits_on_both_sides():
    text = "乙赌资100元\r\n   0元为找零。"
    cut = text.index("\r")
    inp = _split_views(text, cut, len("\r\n   "))
    on = build_packet(text, inp, record_id="R1", layout_wraps=True)
    assert [q["raw"] for q in on["quantities"] if q["type"] == "amount"] == ["100元", "0元"]
    assert len(on["visible_spans"]) == 2


def test_layout_wrap_inside_chinese_numerals_is_joined():
    text = "乙赌资人民币二千三百\r\n   一十元，甲赌资50元。"
    cut = text.index("\r")
    inp = _split_views(text, cut, len("\r\n   "))
    on = build_packet(text, inp, record_id="R1", layout_wraps=True)
    assert [q["engine_projection"]["min"] for q in on["quantities"] if q["type"] == "amount"] == [2310.0, 50.0]


def test_layout_wrap_between_unrelated_lines_is_not_joined():
    text = "乙于2022年\r\n   一同前往赌博。"
    cut = text.index("\r")
    inp = _split_views(text, cut, len("\r\n   "))
    assert len(build_packet(text, inp, record_id="R1", layout_wraps=True)["visible_spans"]) == 2


def test_unit_on_next_line_after_table_pipe_is_joined():
    text = "乙机内的壹仟肆佰玖拾柒 |\r\n|元人民币。"
    cut = text.index(" |")
    inp = _split_views(text, cut, len(" |\r\n|"))
    on = build_packet(text, inp, record_id="R1", layout_wraps=True)
    assert [q["engine_projection"]["min"] for q in on["quantities"] if q["type"] == "amount"] == [1497.0]

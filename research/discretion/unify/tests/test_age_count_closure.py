from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiment_age_count_closure import age_prediction, count_candidates


def packet(events: list[str], birth: str = "1990-01-18") -> dict:
    views = [
        {"span_id": "meta", "zone": "meta"},
        {"span_id": "facts", "zone": "facts"},
    ]
    birth_q = {"candidate_id": "birth", "type": "date", "role_hint": "birth",
               "parse_status": "resolved", "raw": "1990年1月18日", "source_span_id": "meta",
               "engine_projection": {"date": birth}, "start": 0, "end": 10}
    event_qs = [{"candidate_id": f"event-{i}", "type": "date", "role_hint": None,
                 "parse_status": "resolved", "raw": value, "source_span_id": "facts",
                 "engine_projection": {"date": value}, "start": 20 + 20 * i,
                 "end": 30 + 20 * i} for i, value in enumerate(events)]
    return {"visible_spans": views, "quantities": [birth_q, *event_qs]}


def test_age_requires_unique_completed_age_from_visible_operands() -> None:
    selected = age_prediction(packet(["2023-01-17", "2023-01-18"]))
    assert selected["status"] == "abstain"
    assert selected["reason"] == "ambiguous_age_or_event"
    exact = age_prediction(packet(["2023-01-18", "2023-02-01"]))
    assert exact["status"] == "selected"
    assert exact["value"] == 33
    assert exact["consistent_operand_pairs"] == 2
    assert exact["birth_operand"]["candidate_id"] == "birth"


def test_age_does_not_use_prior_or_identity_dates_as_event() -> None:
    value = packet([])
    value["quantities"].append({"candidate_id": "prior", "type": "date", "role_hint": "prior_penalty",
                                "parse_status": "resolved", "raw": "2023年1月18日", "source_span_id": "facts",
                                "engine_projection": {"date": "2023-01-18"}})
    assert age_prediction(value)["status"] == "abstain"


def test_count_candidates_require_exact_person_unit() -> None:
    quantities = [{"type": "count", "parse_status": "resolved", "unit": unit,
                   "engine_projection": {"exact": exact}} for unit, exact in
                  (("人", True), ("人", False), ("次", True))]
    assert count_candidates({"quantities": quantities}) == quantities[:1]

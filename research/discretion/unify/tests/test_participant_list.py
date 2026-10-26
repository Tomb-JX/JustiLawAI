from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiment_participant_list import candidate_lists, proposed_count


def packet(text: str, quantities: list[dict] | None = None) -> dict:
    return {"source": {"text_sha256": hashlib.sha256(text.encode()).hexdigest()},
            "visible_spans": [{"span_id": "s1", "zone": "facts", "start": 0,
                               "end": len(text), "quote": text}],
            "quantities": quantities or []}


def test_repeated_redacted_surfaces_are_separate_list_slots() -> None:
    text = "杨**、陈**、杨**、杨**在院内赌博。"
    proposals = candidate_lists(packet(text), "杨**")
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["value"] == 4
    assert proposal["masked_surface_collision"] is True
    assert len(proposal["participation_edges"]) == 4
    for mention in proposal["mentions"]:
        assert text[mention["start"]:mention["end"]] == mention["raw"]


def test_leading_conjoined_person_is_counted() -> None:
    result = proposed_count(packet("李xx与李x、王x、张x在屋内打麻将。"), "王x")
    assert result["status"] == "selected"
    assert result["value"] == 4
    assert [x["raw"] for x in result["candidate"]["mentions"]] == ["李xx", "李x", "王x", "张x"]


def test_open_list_and_explicit_conflict_abstain() -> None:
    assert proposed_count(packet("张x、王x、李x等人赌博。"), "王x")["status"] == "abstain"
    count = {"type": "count", "parse_status": "resolved", "unit": "人",
             "role_hint": "participant_count", "engine_projection": {"exact": True, "min": 5}}
    result = proposed_count(packet("张x、王x、李x在屋内赌博。", [count]), "王x")
    assert result["status"] == "abstain"
    assert result["reason"] == "explicit_count_conflict"


def test_target_must_be_in_list() -> None:
    assert proposed_count(packet("张x、王x、李x在屋内赌博。"), "赵x")["status"] == "abstain"

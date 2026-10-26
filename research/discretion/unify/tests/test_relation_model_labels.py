from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from durable_calls import DurableCalls
from evaluate_relation_model_labels import amount_key, model_value, score, vote
from experiment_relation_edges import agreed_edges, choose, edge_label, utility


def test_point_amount_equals_bare_value():
    assert amount_key({"min": 150, "max": 150}) == amount_key(150) == "amount:150"
    assert amount_key({"min": "1.50E+2", "max": None}) == "amount:150"
    assert amount_key({"min": 100, "max": 200}) == "amount:100-200"


def test_vote_needs_strict_majority():
    a, b = ("selected", "amount:150"), ("absent", None)
    assert vote([a, b]) is None
    assert vote([a, b, a]) == a
    assert vote([a, b, ("uncertain", None)]) is None


def test_age_from_operands_and_ambiguous_birth_month():
    qs = {"b": {"type": "date", "role_hint": "birth", "parse_status": "resolved", "raw": "1990年1月18日",
                "engine_projection": {"date": "1990-01-18"}},
          "m": {"type": "date", "role_hint": "birth", "parse_status": "resolved", "raw": "1990年5月",
                "engine_projection": {"date": "1990-05-01"}},
          "e": {"type": "date", "parse_status": "resolved", "raw": "2023年5月8日",
                "engine_projection": {"date": "2023-05-08"}}}
    item = {"status": "selected", "candidate_id": None, "birth_candidate_id": "b", "event_date_candidate_id": "e"}
    assert model_value("age", item, qs, {}) == ("selected", "int:33")
    # Born some day in May 1990 and event on 8 May: age 32 or 33 cannot be recomputed uniquely.
    assert model_value("age", {**item, "birth_candidate_id": "m"}, qs, {}) == ("uncertain", None)


def test_score_separates_wrong_value_from_abstain():
    rows = [{"consensus": ("selected", "x"), "chain": "x"},
            {"consensus": ("selected", "x"), "chain": "y"},
            {"consensus": ("selected", "x"), "chain": None},
            {"consensus": ("absent", None), "chain": "y"},
            {"consensus": ("absent", None), "chain": None},
            {"consensus": None, "chain": "x"}]
    s = score(rows)
    assert (s["tp"], s["wrong_value"], s["abstain_on_positive"], s["output_on_absent"], s["tn"]) == (1, 1, 1, 1, 1)
    assert s["no_scorable_consensus"] == 1 and s["precision"] == round(1 / 3, 3) and s["recall"] == round(1 / 3, 3)


def test_abandon_unknown_books_full_reservation(tmp_path):
    calls_dir = tmp_path / "calls"
    calls_dir.mkdir()
    (calls_dir / "attempts.jsonl").write_text(json.dumps(
        {"event": "submitted", "key": "k", "attempt_id": "k:1", "reservation": 0.5,
         "provider": "x", "model": "m", "context": {}, "request_hash": "h", "price": {}}) + "\n", "utf-8")
    provider = SimpleNamespace(base_url="https://example.invalid", model="m", max_tokens=10, temperature=0)
    calls = DurableCalls(calls_dir, {"x": provider}, prices={}, cap=1.0, max_calls=5, max_input_bytes=100)
    assert "k" in calls.unknown and calls.abandon_unknown() == 1 and "k" not in calls.unknown
    reopened = DurableCalls(calls_dir, {"x": provider}, prices={}, cap=1.0, max_calls=5, max_input_bytes=100)
    assert reopened.reserved == 0.5 and not reopened.unknown and reopened.abandon_unknown() == 0


def edge(cid, decision="asserted", roles=("personal_stake",), owner="target"):
    return {"candidate_id": cid, "decision": decision, "roles": list(roles), "owner": owner}


def test_agreed_edges_require_same_roles_and_owner():
    a = {"candidate_edges": [edge("Q1"), edge("Q2"), edge("Q3", "irrelevant", ()), edge("Q4", "uncertain", ())]}
    b = {"candidate_edges": [edge("Q1"), edge("Q2", owner="other"), edge("Q3", "irrelevant", ("other",)),
                             edge("Q4", "uncertain", ())]}
    agreed = agreed_edges({"bailian": a, "deepseek": b})
    # Q2 disagrees on owner; Q4 agrees only on "uncertain", which is not a label.
    assert set(agreed) == {"Q1", "Q3"}
    assert edge_label(agreed["Q1"], "personal_stake") is True
    assert edge_label(agreed["Q3"], "onsite_stake_total") is False
    assert edge_label(edge("Q5", owner="other"), "personal_stake") is False
    assert edge_label(None, "personal_stake") is None


def test_selection_prefers_frozen_chain_unless_strictly_better():
    safe = {"tp": 4}
    noisy = {"tp": 6, "wrong_value": 1, "output_on_absent": 5}
    assert utility(safe) == 4 and utility(noisy) == -6
    report = {"fields": {"personal_stake": {"frozen_chain": {"all": {**safe, "f1": 0.44}},
                                            "local/field": {"all": {**noisy, "f1": 0.46}}},
                         "age": {"derive_only": {"tp": 3, "f1": 1.0}, "derive+stated_fallback": {"tp": 3, "f1": 1.0}}}}
    assert choose(report) == {"personal_stake": "frozen_chain", "age": "derive_only"}
    assert choose(report, "f1")["personal_stake"] == "local/field"


def amount_q(cid, value, start):
    return {"candidate_id": cid, "type": "amount", "parse_status": "resolved", "start": start,
            "engine_projection": {"min": value, "max": value}}


def joint_item(refs):
    packet = {"quantities": [amount_q("Q1", 3910, 0), amount_q("Q2", 570, 20), amount_q("Q3", 3910, 40)]}
    return {"id": "r", "packet": packet, "record": {}, "refs": refs}


def test_node_roles_from_majority_fields():
    from experiment_joint_amount_roles import node_roles
    refs = {"personal_stake": {"consensus": ("selected", "amount:570"), "candidate_ids": {"Q2"}},
            "onsite_stake_total": {"consensus": ("selected", "amount:3910"), "candidate_ids": {"Q1"}}}
    # Q3 repeats the onsite value without being chosen: unlabeled, not a false negative.
    assert node_roles(joint_item(refs)) == {"Q1": "onsite", "Q2": "personal", "Q3": None}
    refs["personal_stake"] = {"consensus": ("selected", "amount:3910"), "candidate_ids": {"Q1"}}
    assert node_roles(joint_item(refs))["Q1"] == "both"
    refs["personal_stake"] = {"consensus": ("uncertain", None), "candidate_ids": set()}
    assert node_roles(joint_item(refs)) == {}


def test_joint_decoder_releases_a_node_claimed_by_both_fields():
    from experiment_joint_amount_roles import Variant
    probs = {"Q1": {"personal": 0.5, "onsite": 0.3, "both": 0.1, "other": 0.1},
             "Q2": {"personal": 0.1, "onsite": 0.2, "both": 0.0, "other": 0.7}}

    class Fixed:
        def predict(self, x):
            return probs[x["id"]]

    item = {"id": "r", "record": {}, "packet": {"quantities": [amount_q("Q1", 100, 0), amount_q("Q2", 900, 9)]}}
    for decoder, onsite in (("softmax", "Q1"), ("softmax_joint", "Q2")):
        v = Variant(decoder, "local")
        v.fn = lambda q, inp, packet: {"id": q["candidate_id"]}
        out = v.predict([item], Fixed())["r"]
        assert out["personal_stake"][2] == "Q1" and out["onsite_stake_total"][2] == onsite


def ownership_packet(text, target_span):
    return {"visible_spans": [{"span_id": "S1", "zone": "facts", "start": 0, "end": len(text), "quote": text}],
            "mentions": [{"mention_id": "M1", "start": target_span[0], "end": target_span[1]}],
            "persons": [{"person_id": "P1", "target": True, "mention_ids": ["M1"]}]}


def test_person_mentions_masked_plain_and_boundaries():
    from ownership import person_mentions
    text = "王某霞与张某福在小康村赌博，张某福持有赌资365元，岑某扬4000元，赵xx通过微信向徐xx转账，其中彭峰赌资100元"
    found = {(m["raw"], m["kind"]) for m in person_mentions(ownership_packet(text, (0, 3)), {"target": "王某霞"})}
    assert ("王某霞", "target") in found and ("张某福", "masked") in found
    assert ("岑某扬", "masked") in found and ("徐xx", "masked") in found and ("彭峰", "plain") in found
    assert not any(raw in {"康村", "向徐xx", "岑某扬4"} for raw, _ in found)


def test_owner_features_nearest_person_and_possession():
    from ownership import owner_features, person_mentions
    text = "王某霞与张某福赌博，张某福持有赌资365元，王某霞持有赌资165元"
    packet = ownership_packet(text, (0, 3))
    mentions = person_mentions(packet, {"target": "王某霞"})
    other = {"source_span_id": "S1", "start": text.index("365"), "end": text.index("365") + 4}
    mine = {"source_span_id": "S1", "start": text.index("165"), "end": text.index("165") + 4}
    x_other, x_mine = owner_features(other, packet, mentions), owner_features(mine, packet, mentions)
    assert x_other["nearest_left_clause:other"] == 1.0 and x_other["nearest_x_possess:other:True"] == 1.0
    assert x_mine["nearest_left_clause:target_like"] == 1.0


def test_parse_alignment_and_merge_offsets():
    from parse_with_toolkits import align, merge, sentences
    text = "张某福持有赌资365元。王某霞持有165元"
    sents = sentences(text)
    assert [s for _, s in sents] == ["张某福持有赌资365元。", "王某霞持有165元"]
    parsed = [{"tokens": ["张某福", "持有", "赌资", "365", "元", "。"], "dep": [[0, 1, "nsubj"]],
               "sdp": [[0, 1, "Agt"]], "srl": [{"pred": 1, "args": [["ARG0", 0, 0]]}], "ner": []},
              {"tokens": ["王某霞", "持有", "165", "元"], "dep": [[0, 1, "nsubj"]], "sdp": [[0, 1, "Agt"]],
               "srl": [], "ner": []}]
    doc = merge(text, sents, parsed)
    assert doc["offsets"][6] == [12, 15] and doc["sent_of"][6] == 1
    assert doc["sdp"][1] == [6, 7, "Agt"]  # second sentence arcs shifted to global token ids
    assert align(text, 0, ["张某福", "不存在"]) is None


def test_graph_path_and_person_end_role():
    from experiment_parser_probe import person_end_role
    from experiment_pair_relations import graph_path
    # 张某福(0) -Agt-> 持有(1) <-Pat- 赌资(2) <-Quan- 365(3)
    arcs = [[0, 1, "Agt"], [2, 1, "Pat"], [3, 2, "Quan"]]
    path = graph_path(arcs, 3, 0)
    assert path == ["↑Quan", "↑Pat", "↓Agt"] and person_end_role(path) == "agt"
    assert graph_path(arcs, 3, 0, limit=2) is None


def test_pair_window_marks_person_and_amount():
    from export_pair_examples import window
    text = "张某福持有赌资365元，王某霞持有165元。"
    packet = {"visible_spans": [{"span_id": "S1", "zone": "facts", "start": 0, "end": len(text), "quote": text}]}
    q = {"start": text.index("365"), "end": text.index("365") + 4}
    person = {"kind": "masked", "surface": "张某福", "mentions": [[0, 3]]}
    w = window({"packet": packet}, q, person)
    assert w["text"].startswith("[人:他人]张某福[/人]持有赌资[额]365元[/额]") and w["person_in_window"]


def test_window_topic_prefix_and_subjectless_flag():
    from export_pair_examples import window
    text = "王某霞与张某福赌博。被查获时持有赌资165元。"
    packet = {"visible_spans": [{"span_id": "S1", "zone": "facts", "start": 0, "end": len(text), "quote": text}]}
    target = {"person_id": "P1", "kind": "target", "surface": "王某霞", "mentions": [[0, 3]]}
    other = {"person_id": "P2", "kind": "masked", "surface": "张某福", "mentions": [[4, 7]]}
    it = {"packet": packet, "persons": [target, other]}
    q = {"start": text.index("165"), "end": text.index("165") + 4}
    plain = window(it, q, target)
    assert plain["text"].startswith("[人:目标]王某霞[/人]")  # extended to the target's sentence
    far = dict(target, mentions=[])  # target never named in this view
    w = window(it, q, far, topic=True, flag_subjectless=True)
    assert w["text"].startswith("[无主][人:目标]王某霞[/人]：") and w["topic_prefixed"]
    assert not window(it, q, other, topic=True)["text"].startswith("[人:")

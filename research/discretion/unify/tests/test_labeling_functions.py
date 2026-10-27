import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import labeling_functions as L
from labeling_functions import ABSTAIN, NO, YES


def record(facts: str, target: str, aliases=(), v1=None, llm=None) -> L.Record:
    text = "某公安局行政处罚决定书\n" + facts
    rec = {"id": "t", "target": target, "aliases": list(aliases), "text_full": text,
           "sentence_view": [{"id": "S1", "type": "meta", "start": 0, "end": 11, "text": text[:11]},
                             {"id": "S2", "type": "facts", "start": 12, "end": len(text), "text": facts}]}
    tmp = Path(__file__).with_name("_lf_tmp.jsonl")
    tmp.write_text(json.dumps(rec, ensure_ascii=False) + "\n", "utf-8")
    try:
        r = next(L.records(tmp, {"t": v1 or {}}, {"t": llm or {}}))
    finally:
        tmp.unlink()
    return r


def votes(r: L.Record, name: str) -> dict[str, int]:
    fn = next(f for n, _t, _g, f in L.registry() if n == name)
    return {q["raw"]: fn(r, i) for i, q in enumerate(r.cands)}


def test_itemised_list_rule_and_caliber_votes():
    r = record("王xx与李xx在家中赌博。现场查获赌资共计900元，其中王xx持有赌资300元，李xx赌资600元。", "王xx")
    assert votes(r, "p_named_stake") == {"900元": ABSTAIN, "300元": YES, "600元": ABSTAIN}
    assert votes(r, "p_other_person")["600元"] == NO
    assert votes(r, "o_stated_total")["900元"] == YES
    assert votes(r, "o_itemised")["300元"] == NO and votes(r, "p_scene_total")["900元"] == NO


def test_unnamed_stake_needs_nobody_else_with_a_stake():
    alone = record("陈某某在家中通过手机赌博，共计充值800元。", "陈某某")
    assert votes(alone, "p_unnamed_stake") == {"800元": YES}
    crowd = record("陈某某与刘xx赌博，查获刘xx持有赌资200元，扣押其个人赌资500元。", "陈某某")
    assert votes(crowd, "p_unnamed_stake")["500元"] == ABSTAIN


def test_definition_takes_the_larger_stated_stake():
    r = record("王xx携带赌资110元参与赌博，被查获时王xx持有赌资125元。", "王xx")
    assert votes(r, "p_definition_larger") == {"110元": NO, "125元": YES}
    single = record("被查获时王xx持有赌资125元。", "王xx")
    assert votes(single, "p_definition_larger") == {"125元": ABSTAIN}


def test_context_votes():
    r = record("王xx赌博，每局输赢10元。决定处以罚款500元。", "王xx")
    assert votes(r, "p_rule_amount")["10元"] == NO
    assert votes(r, "p_fine_clause")["500元"] == NO and votes(r, "p_fine_clause")["10元"] == ABSTAIN


def test_model_and_llm_votes_compare_values():
    v1 = {"personal_stake": {"frozen_chain": {"value": "amount:300"}, "softmax/semantic": {"value": None}}}
    llm = {"bailian": {"personal_stake": {"status": "absent"}, "onsite_stake_total": {"status": "uncertain"}}}
    r = record("现场查获赌资共计900元，其中王xx持有赌资300元。", "王xx", v1=v1, llm=llm)
    assert votes(r, "p_v1_chain") == {"900元": NO, "300元": YES}
    assert set(votes(r, "p_v1_softmax").values()) == {ABSTAIN}
    assert set(votes(r, "p_llm_qwen").values()) == {NO}
    assert set(votes(r, "o_llm_qwen").values()) == {ABSTAIN}
    assert set(votes(r, "p_llm_deepseek").values()) == {ABSTAIN}

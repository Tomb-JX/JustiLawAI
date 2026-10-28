import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import personal_attribution as pa
from personal_attribution import RESULT, STAKE, UNNAMED, attribution_of, name_patterns


def att(text: str, raw: str, target: str, aliases=()) -> str | None:
    return attribution_of(text, text.index(raw), name_patterns(target, list(aliases)))


def test_masked_name_matches_other_mask_forms():
    p = name_patterns("钱**", [])
    assert p[0].search("其中钱xx的赌资") and p[0].search("钱某某持有") and p[0].search("钱x赌资")
    assert not name_patterns("徐某枝", [])[0].search("徐某林")


def test_named_stake_in_an_itemised_list():
    t = "现场扣押王xx赌资370元，施xx赌资500元，周xx赌资700元，赵xx赌资280元。"
    assert att(t, "700元", "周xx") == STAKE
    assert att(t, "500元", "周xx") is None
    assert att("在张萍波的身上查获赌资人民币60元。", "60元", "张萍波") == STAKE
    assert att("从王奇处查获赌资645元。", "645元", "王奇") == STAKE
    assert att("钱xx被查获赌资四万八千九百九十四元。", "四万八千九百九十四元", "钱**") == STAKE


def test_connector_must_be_short_and_plain():
    assert att("周xx合计输3100元，封伟合计赢550元。", "3100元", "周**") is None
    assert att("吴征输了95元，杨某毅赢了210元。", "95元", "吴征") == RESULT


def test_unnamed_stake_and_other_people():
    assert att("并当场扣押其个人赌资人民币4510元。", "4510元", "陈科锋") == UNNAMED
    assert att("被查获时身上有赌资1800元。", "1800元", "王嘉全") == UNNAMED
    assert att("当场查获应新法个人赌资715元。", "715元", "宋建平") is None
    assert att("每次充值10元，共计充值80元。", "10元", "邓**") is None
    assert att("每次充值10元，共计充值80元。", "80元", "邓**") == UNNAMED


def q(start, v):
    return {"candidate_id": f"Q-{v}", "start": start, "end": start + len(f"{v}元"), "raw": f"{v}元",
            "engine_projection": {"min": v, "max": v}}


def run(text, target, values, monkeypatch):
    cands = [q(text.index(f"{v}元"), v) for v in values]
    monkeypatch.setattr(pa, "amounts_of", lambda packet: cands)
    return pa.decide({}, {"text_full": text, "target": target, "aliases": []})


def test_decide(monkeypatch):
    t = "现场扣押王xx赌资370元，周xx赌资700元。"
    assert run(t, "周xx", [370, 700], monkeypatch)["value"] == {"min": 700, "max": 700}
    t = "盛为忠携带赌资110元，赢15元，被公安机关查获时持赌资125元。"
    assert run(t, "盛为忠", [110, 15, 125], monkeypatch)["reason"] == "carried_and_remaining"
    t = "期间钱巨丰输了320元，被当场查获，并从钱巨丰处查获赌资3880。"
    assert run(t, "钱巨丰", [320], monkeypatch)["status"] == "unresolved"
    t = "当日曾××输了15800元。"
    assert run(t, "曾**", [15800], monkeypatch)["reason"] == "explicit_result"

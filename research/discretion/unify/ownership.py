"""Person mentions and amount-ownership features over a supply packet.

Mentions are proposals, not decisions: masked names, surname-led plain names in a
person context, role nouns and the packet's target mentions. Whose an amount is
gets decided by a learned model over the features below and is scored against
A/B-agreed owner edges. Coordinates are global source offsets.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from jionlp.rule.rule_pattern import CHINESE_FAMILY_NAME, TWO_CHAR_CHINESE_FAMILY_NAME

# jionlp omits surnames that are also common characters (马周黄林胡高孙...); add the most common ones back.
COMMON_SURNAMES = ("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁"
                   "任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤")
SINGLE = sorted(set(CHINESE_FAMILY_NAME[1:-1].split("|")) | set(COMMON_SURNAMES), key=len, reverse=True)
SURNAME = "(?:" + TWO_CHAR_CHINESE_FAMILY_NAME + "|" + "|".join(SINGLE) + ")"
# 史某1 carries a digit only right after 某; 岑某扬4000元 must not swallow the amount's first digit.
MASKED_NAME = re.compile(SURNAME + r"(?:某(?:某|[一-鿿]|\d(?![\d.元万]))?|[一-鿿]?(?:[xX]{1,3}|\*{1,3}))")
PREPOSITION = set("向于与和同及被将把给从对跟由")
PLAIN_NAME = re.compile(SURNAME + r"[一-鿿]{1,2}")
ROLE_NOUN = re.compile(r"(?<!被)(?:申请人|第三人|同案人|违法行为人|违法嫌疑人|犯罪嫌疑人|被处罚人|当事人)")
PLACE_NEXT = set("村镇县市区路街乡店厂室馆屯组号楼巷院场所局站省州队庄湾沟河山桥")
NOT_GIVEN = set("元万千百十亿块钱人次场名个赌参打玩")
CUE_START = set("赌提持携输赢等在和与将被参以通使向的分各共现身伙于从为")
PERSON_PREV = set("、和与同及中伙，,：:；;")
PERSON_NEXT = ("赌资", "持有", "携带", "身上", "输", "赢", "、", "和", "与", "等", "参与", "被", "在", "分别",
               "各", "的", "共", "现场", "通过", "使用", "向", "将", "以", "（", "(", "，")
POSSESS = ("持有", "携带", "身上", "赌资", "输", "赢", "转账", "下注", "押注", "充值", "购买", "拿")
SCENE = ("共", "现场", "累计", "合计", "总", "查获", "缴获", "收缴")
DISTRIBUTIVE = ("每人", "各自", "分别", "均", "各")
CLAUSE = re.compile(r"[，,。；;：:！？!?\n]")
SENTENCE = re.compile(r"[。；;！？!?\n]")


@lru_cache(maxsize=1)
def dictionary_words() -> frozenset[str]:
    import jionlp
    path = Path(jionlp.__file__).parent / "dictionary" / "chinese_word_dictionary.txt"
    return frozenset(line.split("\t", 1)[0] for line in path.read_text("utf-8").splitlines() if line)


def person_mentions(packet: dict, inp: dict) -> list[dict]:
    names = {n for n in (inp["target"], *(inp.get("aliases") or ())) if n}
    target_spans = [(m["start"], m["end"]) for m in packet["mentions"]
                    if any(p["target"] and m["mention_id"] in p["mention_ids"] for p in packet["persons"])]
    found = [{"start": s, "end": e, "raw": inp_text(packet, s, e), "kind": "target"} for s, e in target_spans]
    words = dictionary_words()
    for view in packet["visible_spans"]:
        if view["zone"] != "facts":
            continue
        text, base = view["quote"], view["start"]
        proposals = []
        for m in MASKED_NAME.finditer(text):
            end = m.end()
            # 王某赌资 / 张某提供: the character after 某 opens the next word, not the given name.
            if "某" in m.group(0) and text[end - 1] in CUE_START and text[end - 2] == "某":
                end -= 1
            start = m.start()
            # 向徐xx: a preposition that is also a surname, followed by the real masked name.
            if text[start] in PREPOSITION and end - start >= 3 and re.fullmatch(MASKED_NAME, text[start + 1:end]):
                start += 1
            proposals.append((start, end, "masked"))
        for m in PLAIN_NAME.finditer(text):
            # A reading followed by a person cue wins (魏新港|赌资 vs 张海|赌资); otherwise the
            # shortest reading preceded by a list/conjunction context.
            prev = text[m.start() - 1:m.start()] if m.start() else ""
            readings = []
            for end in (m.start() + 2, m.end()) if m.end() - m.start() == 3 else (m.end(),):
                raw, nxt = text[m.start():end], text[end:end + 2]
                # 1000余元 / 于赌博: a unit or the start of a cue word right after the surname is not a given name.
                if raw in words or nxt[:1] in PLACE_NEXT or raw[-1] in PLACE_NEXT or raw[1] in NOT_GIVEN:
                    continue
                readings.append((end, nxt.startswith(PERSON_NEXT)))
            cued = [end for end, cue in readings if cue]
            if cued:
                proposals.append((m.start(), cued[0], "plain"))
            elif readings and prev in PERSON_PREV:
                proposals.append((m.start(), readings[0][0], "plain"))
        for m in ROLE_NOUN.finditer(text):
            proposals.append((m.start(), m.end(), "role:" + m.group(0)))
        for s, e, kind in proposals:
            gs, ge = base + s, base + e
            if text[e:e + 1] in PLACE_NEXT and kind != "masked":
                continue
            if any(not (ge <= a or gs >= b) for a, b in [(f["start"], f["end"]) for f in found]):
                continue
            raw = text[s:e]
            # A masked surface equal to the target's (e.g. 韦** vs 韦**) cannot be told apart; it counts as target.
            found.append({"start": gs, "end": ge, "raw": raw, "kind": "target" if raw in names else kind})
    return sorted(found, key=lambda m: m["start"])


def inp_text(packet: dict, start: int, end: int) -> str:
    view = next((v for v in packet["visible_spans"] if v["start"] <= start and end <= v["end"]), None)
    return view["quote"][start - view["start"]:end - view["start"]] if view else ""


def owner_class(kind: str | None) -> str:
    if kind is None:
        return "none"
    if kind == "target" or kind == "role:申请人" or kind == "role:违法行为人" or kind == "role:被处罚人":
        return "target_like"
    if kind.startswith("role:"):
        return "role_other"
    return "other"


def bounds(text: str, pos: int, pattern: re.Pattern) -> tuple[int, int]:
    left = max((m.end() for m in pattern.finditer(text, 0, pos)), default=0)
    right = next((m.start() for m in pattern.finditer(text, pos)), len(text))
    return left, right


def owner_features(q: dict, packet: dict, mentions: list[dict]) -> dict[str, float]:
    view = next(v for v in packet["visible_spans"] if v["span_id"] == q["source_span_id"])
    text, base = view["quote"], view["start"]
    a = q["start"] - base
    cl, cr = bounds(text, a, CLAUSE)
    sl, sr = bounds(text, a, SENTENCE)
    local = [m for m in mentions if base <= m["start"] and m["end"] <= base + len(text)]
    in_clause = [m for m in local if base + cl <= m["start"] and m["end"] <= base + cr]
    in_sentence = [m for m in local if base + sl <= m["start"] and m["end"] <= base + sr]
    left = [m for m in in_sentence if m["end"] <= q["start"]]
    nearest = left[-1] if left else None
    x = {}
    kind = owner_class(nearest["kind"]) if nearest else "none"
    clause_left = [m for m in in_clause if m["end"] <= q["start"]]
    x["nearest_left_sentence:" + kind] = 1.0
    x["nearest_left_clause:" + (owner_class(clause_left[-1]["kind"]) if clause_left else "none")] = 1.0
    if nearest:
        gap = text[nearest["end"] - base:a]
        dist = len(gap)
        x["nearest_dist:" + ("0-4" if dist <= 4 else "5-12" if dist <= 12 else "13+")] = 1.0
        possess = any(c in gap for c in POSSESS)
        scene = any(c in gap for c in SCENE)
        x["gap_possess:" + str(possess)] = 1.0
        x["gap_scene:" + str(scene)] = 1.0
        x["nearest_x_possess:" + kind + ":" + str(possess)] = 1.0
        x["nearest_x_scene:" + kind + ":" + str(scene)] = 1.0
        distributive = any(c in gap for c in DISTRIBUTIVE)
        x["gap_distributive:" + str(distributive)] = 1.0
        x["nearest_x_distributive:" + kind + ":" + str(distributive)] = 1.0
        x["gap_has_other_person:" + str(any(nearest["end"] <= m["start"] < q["start"] for m in in_sentence
                                            if m is not nearest))] = 1.0
    right = [m for m in in_clause if m["start"] >= q["end"]]
    x["right_clause_person:" + (owner_class(right[0]["kind"]) if right else "none")] = 1.0
    others = {m["raw"] for m in in_sentence if owner_class(m["kind"]) in {"other", "role_other"}}
    x["sentence_others:" + ("0" if not others else "1" if len(others) == 1 else "2-3" if len(others) <= 3 else "4+")] = 1.0
    x["sentence_has_target:" + str(any(owner_class(m["kind"]) == "target_like" for m in in_sentence))] = 1.0
    doc_others = {m["raw"] for m in mentions if owner_class(m["kind"]) == "other"}
    x["doc_others:" + ("0" if not doc_others else "1" if len(doc_others) == 1 else "2-3" if len(doc_others) <= 3 else "4+")] = 1.0
    x["qizhong_before:" + str("其中" in text[cl:a] or "其中" in text[max(0, cl - 4):cl])] = 1.0
    return x

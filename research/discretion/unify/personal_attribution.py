"""Personal stake by explicit attribution: "查获<target>(持有的/个人/身上)赌资X元".

On the p3p7 dev pool most missed personal stakes (163 with a value, routes bound 34) are stated
in one fixed shape: a seizure verb, the target's name, a short connector and the amount, often
inside an itemised list of other people's money. This rule binds only stated attributions:

  - named: the amount's sub-clause (text since the last ，。；、) names the target (full name, alias,
    or masked form: "钱**" matches "钱xx"/"钱某某"), followed only by a connector
    (的/持有的/个人/身上/被查获/有…赌资);
  - unnamed: stake wording without any name ("扣押其个人赌资X元", "被查获时身上有赌资X元",
    "共计充值X元"), used when nobody else in the text has a stake of their own;
  - result: the target's stated win/loss ("输了X元"), used only when the text states no seized
    stake at all.

Two different values of the deciding kind, or a carried amount next to a different remaining
amount ("携带赌资110元 … 查获时持赌资125元"), go to a person: the reviewers themselves split on
which one counts. Deterministic, no model.
"""
from __future__ import annotations

import re

from experiment_relation_edges import amounts_of

STAKE = "stake"
UNNAMED = "unnamed"
RESULT = "result"

_MASK = "xX×*＊ｘ某"
_WRAP = re.compile(r"[\s|]+")
_SEP = re.compile(r"[，。；、,;：:（(）)]")
_CONNECTOR = re.compile(r"(?:的|持有|随身|携带|个人|本人|自己|身上|身边|身|面前|有|被|查获|扣押|缴获|查扣|收缴|用于赌博|"
                        r"涉案|涉嫌|仍|剩余|尚余|处|赌资|为|是|共|达|累计|人民币|现金|筹码|价值|充值|金额|上分|"
                        r"输|赢|了|在其|实际|应|赌博时|时)*")
_STAKE_WORD = re.compile(r"赌资|持有|携带|身上|身边|筹码|面前|充值|上分")
_RESULT_WORD = re.compile(r"输|赢")
_UNNAMED_STAKE = re.compile(r"(?:其|个人|身上|身|身边|随身|携带|持|尚余|剩余|仍持有)(?:有|的|携带的)?(?:涉嫌)?赌资?"
                            r"(?:为|达|累计为)?(?:人民币|现金)?$|(?:共计|总计|累计|共)充值(?:人民币|金额为?)?$")
_ANY_MASKED = re.compile(f"[\\u4e00-\\u9fa5][{re.escape(_MASK)}]{{1,3}}")
_OTHER_NAMED = re.compile(r"(?:查获|扣押|缴获|查扣|收缴|保全|在|从)?([一-龥]{2,3})"
                          r"(?:持有|个人|的赌资|身上|身边|处|随身|携带)")
_NOT_NAME_CHARS = set("赌资场获押缴收总共计现内机当涉嫌余其个人身上查扣有被时为行")
_SEIZED_STAKE = re.compile(r"(?:查获|扣押|缴获|查扣|收缴)[^。；]{0,16}(?:赌资|筹码)")


def name_patterns(target: str, aliases: list[str]) -> list[re.Pattern]:
    """Full names match literally; in a masked name each mask run matches 1–3 mask characters."""
    out = []
    for name in [target, *aliases]:
        name = (name or "").strip()
        if len(name) < 2:
            continue
        pieces = [f"[{re.escape(_MASK)}]{{1,3}}" if part[0] in _MASK else re.escape(part)
                  for part in re.split(f"([{re.escape(_MASK)}]+)", name) if part]
        out.append(re.compile("".join(pieces) + f"(?![{re.escape(_MASK)}])"))
    return out


def _seg(text: str, start: int) -> str:
    """The amount's sub-clause up to the amount, layout wraps removed."""
    return _SEP.split(_WRAP.sub("", text[max(0, start - 40):start]))[-1]


def _other_person(seg: str, patterns: list[re.Pattern]) -> bool:
    if any(p.search(seg) for p in patterns):
        return False
    if any(not any(p.fullmatch(m.group(0)) for p in patterns) for m in _ANY_MASKED.finditer(seg)):
        return True
    return any(not set(m.group(1)) & _NOT_NAME_CHARS for m in _OTHER_NAMED.finditer(seg))


def attribution_of(text: str, start: int, patterns: list[re.Pattern]) -> str | None:
    """STAKE / UNNAMED / RESULT for the amount at `start`, else None."""
    seg = _seg(text, start)
    hits = [m for p in patterns for m in p.finditer(seg)]
    if not hits:
        if re.search(r"每|单次|单局", seg) or _other_person(seg, patterns):
            return None
        return UNNAMED if _UNNAMED_STAKE.search(seg) else None
    connector = seg[max(m.end() for m in hits):]
    if len(connector) > 14 or _CONNECTOR.fullmatch(connector) is None:
        return None
    if _STAKE_WORD.search(connector):
        return STAKE
    if _RESULT_WORD.search(connector):
        return RESULT
    return STAKE if connector == "" and re.search(r"其中|赌资", text[max(0, start - 60):start]) else None


def _key(value: dict) -> tuple:
    return (str(value.get("min")), str(value.get("max")))


def decide(packet: dict, record: dict) -> dict:
    """bound when the deciding kind (named stake, else unnamed stake, else result) has exactly one value."""
    text = record["text_full"]
    patterns = name_patterns(record.get("target") or "", list(record.get("aliases") or []))
    found = {STAKE: {}, UNNAMED: {}, RESULT: {}}
    others_have_stakes = False
    for q in amounts_of(packet):
        if _WRAP.sub("", text[q["end"]:q["end"] + 4]).startswith("面值"):
            continue  # "80元面值的筹码": a chip denomination
        kind = attribution_of(text, q["start"], patterns)
        if kind:
            found[kind].setdefault(_key(q["engine_projection"]), q)
        elif _other_person(_seg(text, q["start"]), patterns):
            others_have_stakes = True
    if others_have_stakes:
        found[UNNAMED] = {}
    if found[STAKE] and set(found[UNNAMED]) - set(found[STAKE]):
        return {"status": "unresolved", "reason": "carried_and_remaining"}
    if found[STAKE] or found[UNNAMED] or _SEIZED_STAKE.search(_WRAP.sub("", text)):
        found[RESULT] = {}
    for kind in (STAKE, UNNAMED, RESULT):
        if len(found[kind]) == 1:
            q = next(iter(found[kind].values()))
            return {"status": "bound", "candidate_id": q["candidate_id"], "value": q["engine_projection"],
                    "reason": f"explicit_{kind}"}
        if len(found[kind]) > 1:
            return {"status": "unresolved", "reason": f"several_{kind}_values"}
    return {"status": "unresolved", "reason": "no_explicit_attribution"}

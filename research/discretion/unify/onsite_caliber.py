"""Onsite-total caliber: is an amount a scene total, one person's money, or a partial pool?

The onsite_stake_total field only takes a total the text states for the whole scene
("共查获赌资X元", "现场赌资共计X元", "总赌资X元", money found inside a gambling machine).
On the p3p7 dev pool the routes failed on exactly this distinction: 13 of 15 onsite outputs on
an absent reference were one person's money ("查获莫xx赌资八百元", "身上有赌资1800元",
"无主赌资5600元"), and 12 abstentions were stated totals listed next to per-person items.

caliber_of() reads only the clause around a candidate; decide() turns the per-candidate
classes into an onsite decision. Deterministic, no model.
"""
from __future__ import annotations

import re

from experiment_relation_edges import amounts_of

TOTAL = "total"            # stated scene total
SEIZED = "seized"          # unattributed seizure ("查获赌资50元"), a total only when nothing is itemised
PERSONAL = "personal"      # one person's money or an item under a total
POOL = "pool"              # 共同/公共/无主 money listed as one part
COIN = "coin"              # "一元硬币732个": the value is a coin count, needs a person
OTHER = "other"

_CLAUSE_END = re.compile(r"[。；;！？]")
_WRAP = re.compile(r"[\s|]+")
_EXPLICIT_SUM = re.compile(r"共计|合计|总计|总共|一共")
_TOTAL = re.compile(r"共计|合计|总计|总共|一共|共查获|共收缴|共扣押|共缴获|总赌资|赌资总[额数计]?|赌资共|共涉赌资|"
                    r"桌面|台面|(?:机|机器|机台|赌博机)[内中里]")
_SCENE_SUM = re.compile(r"总(?:共)?输赢|(?:一场|全场|本场|整场)赌资")
_POOL = re.compile(r"共同|公共|无主|共有|公款")
_ITEM = re.compile(r"其中|分别|各自|每人|个人|本人|带了|带着|剩余|尚余|余下|身上|身边|随身|持有|携带|所持|口袋|钱包|手中|手上")
_MASKED = re.compile(r"[一-龥][xX×*＊ｘ某]{1,3}")
_NAMED = re.compile(r"(?:查获|扣押|收缴|缴获|保全|在)([一-龥]{2,3})(?:的|身上|处)?(?:个人)?(?:赌资|持有|携带)")
_LEAD_NAME = re.compile(r"(?:违法行为人)?([一-龥]{2,3})的?(?:个人)?赌资")
_NOT_NAME_CHARS = set("赌资场获押缴收总共计现内机当涉嫌违法余替代")
_STAKE_CONTEXT = re.compile(r"赌资|赌款|查获|缴获|扣押|收缴|清点|机[内中里]")
_NOT_STAKE = re.compile(r"输了?|赢了?|投注|充值|提现|盈利|中奖|返水|获利|流水|抽头|台费|水钱|头钱|台钱|水子|违法所得")
_SEIZE = re.compile(r"查获|扣押|收缴|缴获|清点|搜出|起获|发现")


def _clause(text: str, start: int, end: int) -> tuple[str, str]:
    """Text from the last clause break to the candidate, and a short tail after it, layout wraps removed."""
    left = max((m.end() for m in _CLAUSE_END.finditer(text, max(0, start - 80), start)), default=max(0, start - 80))
    return _WRAP.sub("", text[left:start]), _WRAP.sub("", text[end:end + 60])


def _named(near: str, names: list[str]) -> bool:
    """A person is named in this stretch: masked name, the target/aliases, or "查获张晶赌资"/"张晶赌资"."""
    lead = _LEAD_NAME.match(near)
    return bool(_MASKED.search(near) or any(n and n in near for n in names)
                or any(not set(m.group(1)) & _NOT_NAME_CHARS for m in _NAMED.finditer(near + "赌资"))
                or lead and not set(lead.group(1)) & _NOT_NAME_CHARS)


def caliber_of(text: str, start: int, end: int, names: list[str], raw: str = "") -> str:
    before, after = _clause(text, start, end)
    near = before[-16:]
    seg = re.split(r"[，,、（(：:]", near)[-1]  # the sub-clause the amount belongs to
    if re.match(r"(?:面值)?硬币", after):
        return COIN
    if raw.endswith("块") and not re.search(r"赌资|人民币|现金|钱", seg):
        return OTHER  # "主板9块"
    if _SCENE_SUM.search(seg):
        return TOTAL
    if (re.search(r"人均|平均|均摊", seg) or _NOT_STAKE.search(seg[-8:])
            or re.match(r"(?:人民币)?(?:兑换|换取|折合)|的?(?:抽头|台费|水钱|头钱)", after)):
        return OTHER
    k = before.rfind("其中")
    if "其中" in near or k >= 0 and not _SEIZE.search(before[k:]):
        return PERSONAL
    # "被查获赌资X元" after "秦x输一百元，" is that person's money.
    named = _named(seg, names) or seg.startswith("被") and _named(near, names)
    total = [m.end() for m in _TOTAL.finditer(seg)]
    pool = [m.end() for m in _POOL.finditer(seg)]
    head = re.match(r"[^。；]{0,16}?[，,。；（(]其中", after)
    if total and (not pool or max(total) > max(pool)) and _STAKE_CONTEXT.search(before):
        return PERSONAL if named and not _EXPLICIT_SUM.search(seg) else TOTAL
    if pool:
        return TOTAL if head else POOL
    if named or _ITEM.search(seg):
        return PERSONAL
    seized = ("赌资" in seg + after[:3] and _SEIZE.search(before) or re.search(r"现场.{0,6}赌资", seg)
              or re.search(r"赌资(?:人民币)?$", seg))
    if seized and head:
        return TOTAL  # "现场查获赌资X元，(赌具…。)其中A赌资…": the itemised sum's head
    if seized:
        return SEIZED
    return OTHER


def classify(packet: dict, record: dict) -> list[dict]:
    text = record["text_full"]
    names = [record.get("target") or ""] + list(record.get("aliases") or [])
    out = []
    for q in amounts_of(packet):
        out.append({"candidate_id": q["candidate_id"], "raw": q["raw"], "value": q["engine_projection"],
                    "caliber": caliber_of(text, q["start"], q["end"], names, q["raw"])})
    return out


def _key(value: dict) -> tuple:
    return (str(value.get("min")), str(value.get("max")))


def decide(cands: list[dict]) -> dict:
    """bound (one total value) | absent (amounts present, none can be a total) | unresolved."""
    totals = {}
    for c in cands:
        if c["caliber"] == TOTAL:
            totals.setdefault(_key(c["value"]), c)
    if len(totals) == 1:
        return {"status": "bound", "candidate": next(iter(totals.values())), "reason": "stated_total"}
    if len(totals) > 1:
        return {"status": "unresolved", "reason": "several_totals"}
    itemised = any(c["caliber"] == PERSONAL for c in cands)
    # A pool ("无主赌资X元") counts as the scene total only when it is the only money found.
    seized = {_key(c["value"]): c for c in cands
              if c["caliber"] == SEIZED or c["caliber"] == POOL and not itemised}
    if len(seized) == 1 and not itemised:
        return {"status": "bound", "candidate": next(iter(seized.values())), "reason": "only_unattributed_money"}
    if seized:
        return {"status": "unresolved", "reason": "seizure_beside_items"}
    if any(c["caliber"] == COIN for c in cands):
        return {"status": "unresolved", "reason": "coin_count"}
    if not cands:
        return {"status": "absent", "reason": "no_amount"}
    return {"status": "absent", "reason": "no_total_expression"}

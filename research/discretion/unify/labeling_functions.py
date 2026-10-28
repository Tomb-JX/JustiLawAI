"""Labeling functions (LFs) for binding v2 weak supervision: vote or abstain per amount candidate.

Two binary tasks are asked of every resolved amount candidate of a record:

  personal : is this amount the target's personal stake (赌资 the target held, put in or won)?
  onsite   : is this amount the stated total of the whole scene?

An LF answers YES, NO or ABSTAIN and stands for one source and one phenomenon. Groups:

  rule      the frozen 10-27 rules (`personal_attribution`, `onsite_caliber`) split into their
            phenomena; the rule code is called, never edited
  context   one non-lexicon context each: a fine clause, a rule amount (每局/单次)
  structure nearest person mention before the amount (regex layer and NER layer separately),
            nearest person mention in the dependency tree (HanLP and LTP separately)
  model     the three binding-v1 routes (frozen chain, softmax/semantic, softmax/semantic_pair)
  llm       qwen3.8-flash and deepseek-flash review4 answers
  definition 赌资 = 投入 + 赢取: of two stake values stated for the target, the larger counts

Votes are compared by value key (`amount_key`), as the record-level reference is: a candidate
with the referenced value is YES even when it is a repeat mention. An LF never reads another
LF's vote, except `definition`, which is defined on the target's stated stakes. The end model
never sees votes (plan §1.5); they only become soft labels through the label model.
"""
from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import onsite_caliber as oc
import personal_attribution as pa
from evaluate_relation_model_labels import amount_key
from experiment_pair_relations import view_of
from experiment_relation_edges import amounts_of
from ownership import SENTENCE, bounds
from ownership import person_mentions as regex_mentions
from person_mentions_ner import CACHE, person_mentions as ner_mentions
from review4 import key_of, task_for
from supply_packet import build_packet

YES, NO, ABSTAIN = 1, 0, -1
TASKS = ("personal", "onsite")
FIELD = {"personal": "personal_stake", "onsite": "onsite_stake_total"}
ROUTES = {"v1_chain": "frozen_chain", "v1_softmax": "softmax/semantic", "v1_pair": "softmax/semantic_pair"}
LLMS = {"qwen": "bailian", "deepseek": "deepseek"}
_FINE = re.compile(r"罚款|罚金|并处|处以|缴纳")
_RULE_AMOUNT = re.compile(r"每|单次|单局")
_MAX_TREE_HOPS = 4


@dataclass
class Record:
    rec: dict
    packet: dict
    cands: list[dict]
    patterns: list[re.Pattern]
    names: list[str]
    regex_people: list[dict]
    ner_people: list[dict]
    v1: dict = field(default_factory=dict)       # field -> {route: proposal}
    llm: dict = field(default_factory=dict)      # provider -> review4 answer
    task: dict = field(default_factory=dict)     # review4 task (candidate list for answer keys)
    memo: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.rec["text_full"]

    def key(self, q: dict) -> str | None:
        return amount_key(q["engine_projection"])


# ---------------------------------------------------------------- shared readings (memoised)

def _attribution(r: Record) -> list[str | None]:
    if "attr" not in r.memo:
        r.memo["attr"] = [pa.attribution_of(r.text, q["start"], r.patterns) for q in r.cands]
    return r.memo["attr"]


def _other_person(r: Record) -> list[bool]:
    if "other" not in r.memo:
        r.memo["other"] = [pa._other_person(pa._seg(r.text, q["start"]), r.patterns) for q in r.cands]
    return r.memo["other"]


def _caliber(r: Record) -> list[str]:
    if "cal" not in r.memo:
        r.memo["cal"] = [oc.caliber_of(r.text, q["start"], q["end"], r.names, q["raw"]) for q in r.cands]
    return r.memo["cal"]


def _face_value(r: Record, i: int) -> bool:
    q = r.cands[i]
    return pa._WRAP.sub("", r.text[q["end"]:q["end"] + 4]).startswith("面值")


def _seized_stake(r: Record) -> bool:
    return bool(pa._SEIZED_STAKE.search(pa._WRAP.sub("", r.text)))


def _sub_clause(r: Record, i: int) -> str:
    return pa._seg(r.text, r.cands[i]["start"])


# ---------------------------------------------------------------- rule group: personal_attribution

def p_named_stake(r: Record, i: int) -> int:
    """"查获<目标>(持有的/个人/身上)赌资X元": the target's name, a connector, a stake word."""
    return YES if _attribution(r)[i] == pa.STAKE and not _face_value(r, i) else ABSTAIN


def p_unnamed_stake(r: Record, i: int) -> int:
    """"扣押其个人赌资X元" with nobody else in the text holding a stake of their own."""
    if _attribution(r)[i] != pa.UNNAMED or _face_value(r, i) or any(_other_person(r)):
        return ABSTAIN
    return YES


def p_stated_result(r: Record, i: int) -> int:
    """"<目标>输了X元" when the text states no seized or held stake at all."""
    attr = _attribution(r)
    if attr[i] != pa.RESULT or _face_value(r, i):
        return ABSTAIN
    if pa.STAKE in attr or pa.UNNAMED in attr or _seized_stake(r):
        return ABSTAIN
    return YES


def p_other_person(r: Record, i: int) -> int:
    """The amount's sub-clause names someone other than the target."""
    return NO if _other_person(r)[i] else ABSTAIN


def p_face_value(r: Record, i: int) -> int:
    """"80元面值的筹码": a chip denomination."""
    return NO if _face_value(r, i) else ABSTAIN


# ---------------------------------------------------------------- rule group: onsite_caliber

def o_stated_total(r: Record, i: int) -> int:
    """"共查获赌资X元" / "现场赌资共计X元" / money inside a machine: a stated scene total."""
    return YES if _caliber(r)[i] == oc.TOTAL else ABSTAIN


def o_only_unattributed(r: Record, i: int) -> int:
    """Unattributed seized money ("查获赌资X元", "无主赌资X元") that is the only money and has one value."""
    cal = _caliber(r)
    if cal[i] not in (oc.SEIZED, oc.POOL) or oc.PERSONAL in cal:
        return ABSTAIN
    values = {r.key(q) for q, c in zip(r.cands, cal) if c in (oc.SEIZED, oc.POOL)}
    return YES if len(values) == 1 else ABSTAIN


def o_itemised(r: Record, i: int) -> int:
    """One person's money or an item under a total ("其中", "身上", a named holder)."""
    return NO if _caliber(r)[i] == oc.PERSONAL else ABSTAIN


def o_pool_beside_items(r: Record, i: int) -> int:
    """"共同/无主赌资X元" listed beside per-person items: a part, not the total."""
    cal = _caliber(r)
    return NO if cal[i] == oc.POOL and oc.PERSONAL in cal else ABSTAIN


def _explicit_other(r: Record, i: int) -> bool:
    """caliber_of returned OTHER on one of its stated grounds, not as its no-evidence fallback."""
    q = r.cands[i]
    if _caliber(r)[i] == oc.COIN:
        return True
    if _caliber(r)[i] != oc.OTHER:
        return False
    before, after = oc._clause(r.text, q["start"], q["end"])
    seg = re.split(r"[，,、（(：:]", before[-16:])[-1]
    return bool(q["raw"].endswith("块") and not re.search(r"赌资|人民币|现金|钱", seg)
                or re.search(r"人均|平均|均摊", seg) or oc._NOT_STAKE.search(seg[-8:])
                or re.match(r"(?:人民币)?(?:兑换|换取|折合)|的?(?:抽头|台费|水钱|头钱)", after))


def o_not_stake(r: Record, i: int) -> int:
    """Not seized money: 人均, 输赢/流水/充值, 抽头, 兑换比例, coin counts, "主板9块"."""
    return NO if _explicit_other(r, i) else ABSTAIN


def p_scene_total(r: Record, i: int) -> int:
    """A stated scene total is not one person's stake."""
    return NO if _caliber(r)[i] == oc.TOTAL else ABSTAIN


def p_not_stake(r: Record, i: int) -> int:
    """人均, 抽头/台费, 兑换比例, coin counts: not a stake (输赢 is excluded: a result can be a stake)."""
    if not _explicit_other(r, i):
        return ABSTAIN
    seg = _sub_clause(r, i)
    return ABSTAIN if re.search(r"输|赢", seg[-8:]) else NO


# ---------------------------------------------------------------- context group

def fine_clause(r: Record, i: int) -> int:
    """The amount sits in a penalty clause ("处以罚款X元", "并处罚款")."""
    q = r.cands[i]
    left = pa._WRAP.sub("", r.text[max(0, q["start"] - 12):q["start"]])
    return NO if _FINE.search(re.split(r"[，。；,;]", left)[-1]) else ABSTAIN


def rule_amount(r: Record, i: int) -> int:
    """A per-round or per-bet amount ("每局", "单次", "单局"), a game rule, not money held."""
    return NO if _RULE_AMOUNT.search(_sub_clause(r, i)) else ABSTAIN


# ---------------------------------------------------------------- structure group

def _nearest_linear(r: Record, i: int, people: list[dict]) -> str | None:
    q = r.cands[i]
    view = view_of(r.packet, q["start"])
    s, _ = bounds(view["quote"], q["start"] - view["start"], SENTENCE)
    left = view["start"] + s
    before = [m for m in people if left <= m["start"] and m["end"] <= q["start"]
              and not m["kind"].startswith("role")]
    if not before:
        return None
    return "target" if max(before, key=lambda m: m["end"])["kind"] == "target" else "other"


def _linear_vote(kind: str | None, task: str) -> int:
    if kind is None:
        return ABSTAIN
    if task == "personal":
        return YES if kind == "target" else NO
    return NO  # a person right before the amount in its sentence: that person's money


def nearest_regex(task: str):
    def lf(r: Record, i: int) -> int:
        return _linear_vote(_nearest_linear(r, i, r.regex_people), task)
    lf.__doc__ = "Nearest person mention before the amount in its sentence, regex person layer."
    return lf


def nearest_ner(task: str):
    def lf(r: Record, i: int) -> int:
        return _linear_vote(_nearest_linear(r, i, r.ner_people), task)
    lf.__doc__ = "Nearest person mention before the amount in its sentence, NER person layer."
    return lf


_PARSES: dict[str, dict] = {}


def load_parses(cache: Path = CACHE) -> None:
    for toolkit in ("hanlp", "ltp"):
        if toolkit in _PARSES:
            continue
        docs = {}
        with (cache / f"{toolkit}.jsonl").open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                docs[d["key"]] = {k: d[k] for k in ("offsets", "sent_of", "dep")}
        _PARSES[toolkit] = docs


def _tree_nearest(r: Record, i: int, toolkit: str) -> str | None:
    """Kind of the person mention closest to the amount in the dependency tree (≤ 4 hops, unique)."""
    import hashlib
    q = r.cands[i]
    view = view_of(r.packet, q["start"])
    doc = _PARSES.get(toolkit, {}).get(hashlib.sha256(view["quote"].encode("utf-8")).hexdigest())
    if doc is None:
        return None
    base, offs, sent = view["start"], doc["offsets"], doc["sent_of"]

    def token_at(a: int, b: int) -> list[int]:
        return [k for k, (s, e) in enumerate(offs) if s < b - base and a - base < e]

    start = token_at(q["start"], q["end"])
    if not start:
        return None
    graph: dict[int, list[int]] = {}
    for d, h, _ in doc["dep"]:
        if 0 <= h < len(offs) and sent[d] == sent[h]:
            graph.setdefault(d, []).append(h)
            graph.setdefault(h, []).append(d)
    dist = {k: 0 for k in start}
    todo = deque(start)
    while todo:
        k = todo.popleft()
        if dist[k] >= _MAX_TREE_HOPS:
            continue
        for n in graph.get(k, ()):
            if n not in dist:
                dist[n] = dist[k] + 1
                todo.append(n)
    best: dict[str, int] = {}
    for m in r.ner_people:
        if m["kind"].startswith("role") or not (base <= m["start"] < base + len(view["quote"])):
            continue
        hops = [dist[k] for k in token_at(m["start"], m["end"]) if k in dist]
        if hops:
            kind = "target" if m["kind"] == "target" else "other"
            best[kind] = min(best.get(kind, 99), min(hops))
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda kv: kv[1])
    if len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def tree_nearest(toolkit: str, task: str):
    def lf(r: Record, i: int) -> int:
        kind = _tree_nearest(r, i, toolkit)
        if kind is None:
            return ABSTAIN
        if task == "personal":
            return YES if kind == "target" else NO
        return NO
    lf.__doc__ = f"Person mention nearest to the amount in the {toolkit} dependency tree."
    return lf


# ---------------------------------------------------------------- model group (binding v1)

def v1_route(route: str, task: str):
    def lf(r: Record, i: int) -> int:
        prop = (r.v1.get(FIELD[task]) or {}).get(route) or {}
        if not prop.get("value"):
            return ABSTAIN
        return YES if prop["value"] == r.key(r.cands[i]) else NO
    lf.__doc__ = f"binding-v1 route {route}: its proposed value."
    return lf


# ---------------------------------------------------------------- llm group

def llm(provider: str, task: str):
    def lf(r: Record, i: int) -> int:
        ans = r.llm.get(provider)
        if not ans:
            return ABSTAIN
        k = key_of(FIELD[task], ans[FIELD[task]], r.task)
        if k == "uncertain":
            return ABSTAIN
        return YES if k == r.key(r.cands[i]) else NO
    lf.__doc__ = f"review4 answer of {provider}: selected value YES, other values and absent NO, uncertain abstains."
    return lf


# ---------------------------------------------------------------- definition group

def p_definition_larger(r: Record, i: int) -> int:
    """赌资 = 投入 + 赢取 (两高 2005 解释第八条): of two different stake values stated for the
    target (carried vs. held at seizure), the larger is the stake and the smaller is not."""
    attr = _attribution(r)
    own = [k for k, a in enumerate(attr) if a in (pa.STAKE, pa.UNNAMED) and not _face_value(r, k)]
    if any(_other_person(r)):
        own = [k for k in own if attr[k] == pa.STAKE]
    values = {r.key(r.cands[k]): float(r.cands[k]["engine_projection"]["min"]) for k in own}
    if i not in own or len(values) < 2:
        return ABSTAIN
    return YES if values[r.key(r.cands[i])] == max(values.values()) else NO


# ---------------------------------------------------------------- registry

LF = tuple  # (name, task, group, fn)


def registry() -> list[LF]:
    out: list[LF] = [
        ("p_named_stake", "personal", "rule", p_named_stake),
        ("p_unnamed_stake", "personal", "rule", p_unnamed_stake),
        ("p_stated_result", "personal", "rule", p_stated_result),
        ("p_other_person", "personal", "rule", p_other_person),
        ("p_face_value", "personal", "rule", p_face_value),
        ("p_scene_total", "personal", "rule", p_scene_total),
        ("p_not_stake", "personal", "rule", p_not_stake),
        ("o_stated_total", "onsite", "rule", o_stated_total),
        ("o_only_unattributed", "onsite", "rule", o_only_unattributed),
        ("o_itemised", "onsite", "rule", o_itemised),
        ("o_pool_beside_items", "onsite", "rule", o_pool_beside_items),
        ("o_not_stake", "onsite", "rule", o_not_stake),
        ("p_definition_larger", "personal", "definition", p_definition_larger),
    ]
    for task in TASKS:
        t = task[0]
        out += [(f"{t}_fine_clause", task, "context", fine_clause),
                (f"{t}_nearest_regex", task, "structure", nearest_regex(task)),
                (f"{t}_nearest_ner", task, "structure", nearest_ner(task)),
                (f"{t}_tree_hanlp", task, "structure", tree_nearest("hanlp", task)),
                (f"{t}_tree_ltp", task, "structure", tree_nearest("ltp", task))]
        out += [(f"{t}_{name}", task, "model", v1_route(route, task)) for name, route in ROUTES.items()]
        out += [(f"{t}_llm_{name}", task, "llm", llm(provider, task)) for name, provider in LLMS.items()]
    out.append(("p_rule_amount", "personal", "context", rule_amount))
    return out


# ---------------------------------------------------------------- loading

def load_v1(path: Path | None) -> dict[str, dict]:
    out = {}
    if path and path.exists():
        for line in path.read_text("utf-8").splitlines():
            row = json.loads(line)
            out[row["id"]] = {b["field"].split(".")[1]: b.get("proposals") or {} for b in row["bindings"]
                              if b["field"] in ("amounts.personal_stake", "amounts.onsite_stake_total")}
    return out


def load_llm(label_dir: Path | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if label_dir and label_dir.exists():
        for p in label_dir.glob("*.json"):
            row = json.loads(p.read_text("utf-8"))
            out.setdefault(row["id"], {})[row["provider"]] = row["answer"]
    return out


def records(inputs: Path, v1: dict, llm_answers: dict, ids: set[str] | None = None):
    load_parses()
    for line in inputs.read_text("utf-8").splitlines():
        rec = json.loads(line)
        if ids is not None and rec["id"] not in ids:
            continue
        packet = build_packet(rec["text_full"], rec, record_id=rec["id"], layout_wraps=True)
        cands = amounts_of(packet)
        if not cands:
            continue
        aliases = list(rec.get("aliases") or [])
        yield Record(rec=rec, packet=packet, cands=cands,
                     patterns=pa.name_patterns(rec.get("target") or "", aliases),
                     names=[rec.get("target") or ""] + aliases,
                     regex_people=regex_mentions(packet, rec), ner_people=ner_mentions(packet, rec),
                     v1=v1.get(rec["id"], {}), llm=llm_answers.get(rec["id"], {}),
                     task=task_for(rec, packet))


def vote_rows(recs, lfs: list[LF]):
    """One row per (record, candidate): value key and every LF's vote per task."""
    for r in recs:
        for i, q in enumerate(r.cands):
            yield {"id": r.rec["id"], "candidate_id": q["candidate_id"], "value": r.key(q),
                   "votes": {name: fn(r, i) for name, _task, _group, fn in lfs}}

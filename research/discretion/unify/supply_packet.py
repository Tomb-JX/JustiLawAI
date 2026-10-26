"""Source-bound candidate packet for S2/L5; proposals never certify semantic binding.

The packet separates document event groups, local scenes, economic items and
quantities. Engine E-05 remains the only field-value policy. This module is
offline and deterministic; ambiguity is recorded instead of guessed away.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation

from element_contract import normalization_spec

VERSION = "supply-binding-0.3"
_NUM = r"[0-9０-９〇零一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟点.,，]+"
MONEY = re.compile(fr"(?:不超过|不低于|至少|不足|不到|超过|逾|约|近)?{_NUM}(?:(?:至|到|[-~～]){_NUM})?[余多]?(?:元|块)(?:以上|以下|左右)?")
COUNT = re.compile(fr"(?:共计|合计|至少|不超过|超过|不足|约)?{_NUM}[余多]?(?:名|位|个)?(?:人|次|场|台|张)")
AGE = re.compile(fr"{_NUM}岁")
TIME = re.compile(r"\d{4}年\d{1,2}月至(?:(?:\d{4}年)?\d{1,2}月)|\d{4}年\d{1,2}月\d{1,2}[日号]|\d{4}年\d{1,2}月|\d{4}年")
DURATION = re.compile(fr"(?:持续|长达|历时)\s*{_NUM}(?:个?月|年|天|日|周)")
_CLAUSE_END = re.compile(r"[。；;\n]|(?<!\d)[，,]|[，,](?!\d)")
# This is used only for negative binding guards. Prefer unresolved to a false
# other-person hit inside ordinary words such as 自己 or 给郑某.
_SIMPLE_PERSON = re.compile(
    r"(?<![\u4e00-\u9fff])[甲乙丙丁戊](?=持有|携带|投入|出资|参与|参赌|使用|在|于|各|[、，,])"
    r"|(?<![\u4e00-\u9fff])[\u4e00-\u9fff]{1,2}某(?=持有|携带|投入|出资|参与|参赌|使用|在|于|各|等|[、，,])")
_BEHAVIOR = re.compile(r"赌博|参赌|赌资|抽头|开设赌场|提供.{0,8}(?:场地|条件)|赌机|投注")
_PRIOR = re.compile(r"曾|此前|前次|上次|既往|历史")
_NEGATION = re.compile(r"未(?:持有|携带|参与|参赌|投入|出资)|没有|不曾|并未")

_ROLE_CUES = (
    ("commission", re.compile(r"抽头|渔利|头钱|水钱|台费|场地费")),
    ("per_bet", re.compile(r"每局|每注|单注|每把")),
    ("onsite_stake_total", re.compile(r"现场.{0,8}(?:查获|扣押|赌资)|查获.{0,8}赌资|赌资.{0,8}(?:收缴|扣押)")),
    ("cumulative_stake", re.compile(r"累计.{0,8}(?:赌资|赌款)|(?:赌资|赌款).{0,8}累计")),
    ("illegal_gain", re.compile(r"违法所得")),
    ("personal_stake", re.compile(r"持有|携带|投入|出资|筹码")),
)
_AMOUNT_FIELD_ROLE = {
    "amounts.personal_stake": "personal_stake",
    "amounts.per_bet": "per_bet",
    "amounts.onsite_stake_total": "onsite_stake_total",
    "amounts.cumulative_stake": "cumulative_stake",
    "amounts.commission": "commission",
    "amounts.illegal_gain": "illegal_gain",
}
_COUNT_FIELD_ROLE = {
    "conduct.times": "times",
    "persons.participant_count": "participant_count",
    "persons.cumulative_participants": "cumulative_participants",
    "persons.abroad_organized_count": "abroad_organized_count",
    "person.age": "age",
}


def _id(prefix: str, *parts: object) -> str:
    value = "|".join(str(p) for p in parts)
    return prefix + "-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _clauses(view: dict):
    value, start = view["text"], 0
    for m in _CLAUSE_END.finditer(value):
        if value[start:m.end()].strip():
            yield view["start"] + start, view["start"] + m.end()
        start = m.end()
    if value[start:].strip():
        yield view["start"] + start, view["end"]


def _actor(prefix: str, target: str, aliases: tuple[str, ...]) -> tuple[str | None, str]:
    """A local actor suggestion, used for negative guards, never approval."""
    tail = prefix[-16:]
    known = sorted({target, *aliases}, key=len, reverse=True)
    hits = [(m.end(), target) for name in known for m in re.finditer(re.escape(name), tail)]
    other = [(m.end(), m.group()) for m in _SIMPLE_PERSON.finditer(tail)
             if m.group() not in known]
    all_hits = sorted(hits + other)
    if not all_hits:
        return None, "unresolved"
    if re.search(r"各|分别|共同|一同|伙同", tail) and hits and other:
        return None, "joint"
    name = all_hits[-1][1]
    return name, "target" if name == target else "other"


def _amount_role(prefix: str) -> str | None:
    if re.search(r"(?:持有|携带|出资|投入)[^，,。；;]{0,16}(?:赌资|赌款|赌注|筹码)?$", prefix):
        return "personal_stake"
    hits = [(m.end(), role) for role, pattern in _ROLE_CUES for m in pattern.finditer(prefix)]
    if not hits:
        return None
    latest = max(pos for pos, _ in hits)
    roles = {role for pos, role in hits if pos == latest}
    return next(iter(roles)) if len(roles) == 1 else None


def _surface_operator(raw: str, *, exact: bool) -> tuple[str, bool, bool, str]:
    if re.search(r"不超过|以下|至多", raw):
        return "<=", True, True, "upper_bound"
    if re.search(r"不足|不到|低于", raw):
        return "<", True, False, "upper_bound"
    if re.search(r"超过|逾", raw):
        return ">", False, False, "lower_bound"
    if re.search(r"至少|不低于|以上", raw):
        return ">=", True, False, "lower_bound"
    if re.search(r"余|多", raw):
        return ">", False, True, "bounded_vague"
    if re.search(r"约|近|左右", raw):
        return "~", True, True, "approximate"
    return ("=", True, True, "exact") if exact else ("range", True, True, "interval")


def _normalized(raw: str, typ: str) -> dict:
    e05 = normalization_spec()
    if typ == "amount":
        value = e05.normalize_amount(raw)
        if value is None:
            return {"parse_status": "unresolved", "reason": "e05_parse_failed"}
        exact = value["min"] == value["max"]
        op, li, ui, kind = _surface_operator(raw, exact=exact)
        return {"parse_status": "resolved", "kind": kind, "lower": str(value["min"]),
                "upper": str(value["max"]) if value["max"] is not None else None,
                "lower_inclusive": li, "upper_inclusive": ui, "operator": op,
                "engine_projection": value}
    if typ in {"count", "age"}:
        value = e05.normalize_count(raw)
        if value is None:
            return {"parse_status": "unresolved", "reason": "e05_parse_failed"}
        op, li, ui, kind = _surface_operator(raw, exact=value["exact"])
        return {"parse_status": "resolved", "kind": kind, "lower": str(value["min"]),
                "upper": str(value["max"]) if value["max"] is not None else None,
                "lower_inclusive": li, "upper_inclusive": ui, "operator": op,
                "engine_projection": value}
    if typ == "date":
        span = e05.normalize_date_range(raw)
        if span is not None:
            return {"parse_status": "resolved", "kind": "calendar_range",
                    "start_date": span["start"].isoformat(), "end_date": span["end"].isoformat(),
                    "precision": "range", "engine_projection": {"days": span["days"]}}
        point = e05.normalize_date(raw)
        if point is not None:
            day, status = point
            return {"parse_status": "resolved", "kind": "calendar_point", "start_date": day.isoformat(),
                    "end_date": day.isoformat(), "precision": "day" if status == "明确" else "coarse",
                    "engine_projection": {"date": day.isoformat(), "status": status}}
        return {"parse_status": "unresolved", "reason": "e05_parse_failed"}
    if typ == "duration":
        value = e05.normalize_duration(re.sub(r"^(?:持续|长达|历时)\s*", "", raw))
        return ({"parse_status": "resolved", "kind": "duration", "days": value,
                 "engine_projection": {"days": value}} if value is not None else
                {"parse_status": "unresolved", "reason": "e05_parse_failed"})
    raise ValueError("unsupported_candidate_type")


def build_packet(text_full: str, inp: dict, *, record_id: str, case_event_id: str | None = None,
                 schema_version: str = "1.1.0") -> dict:
    """Produce source-anchored proposals from an already allowed facts/meta view."""
    if not isinstance(text_full, str) or not isinstance(inp, dict):
        raise ValueError("invalid_supply_input")
    views = inp.get("sentence_view") or []
    target = inp.get("target") or ""
    aliases = tuple(inp.get("aliases") or ())
    if not target or target not in text_full or not views:
        raise ValueError("supply_target_or_view_missing")
    source_hash = hashlib.sha256(text_full.encode("utf-8")).hexdigest()
    if inp.get("source_sha256") and inp["source_sha256"] != source_hash:
        raise ValueError("supply_source_hash_mismatch")
    packet = {"binding_contract_version": VERSION,
              "source": {"record_id": record_id, "case_event_id": case_event_id,
                         "target_id": _id("P", source_hash, target), "text_sha256": source_hash,
                         "view_hash": inp.get("view_hash"), "schema_version": schema_version,
                         "fact_view_version": inp.get("fact_view_version")},
              "visible_spans": [], "mentions": [], "persons": [], "scenes": [],
              "economic_items": [], "claims": [], "quantities": [], "relations": [],
              "derivations": [], "bindings": [], "field_disposition": {}, "unresolved": []}
    target_id = packet["source"]["target_id"]
    packet["persons"].append({"person_id": target_id, "target": True, "mention_ids": []})
    occupied = []
    for view in views:
        a, b = view.get("start"), view.get("end")
        if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text_full)
                or text_full[a:b] != view.get("text") or view.get("type") not in {"facts", "meta"}):
            raise ValueError("supply_view_not_source_grounded")
        if any(a < y and x < b for x, y in occupied):
            raise ValueError("supply_view_overlap")
        occupied.append((a, b))
        sid = view.get("id") or _id("S", source_hash, a, b)
        packet["visible_spans"].append({"span_id": sid, "sentence_id": view.get("sentence_id"),
                                        "start": a, "end": b, "quote": text_full[a:b],
                                        "zone": view["type"], "source_zone": view.get("source_zone", view["type"]),
                                        "role": view.get("fact_role", "identity" if view["type"] == "meta" else "legacy_sentence"),
                                        "source": view.get("projection_source", "zone")})
        for name in sorted({target, *aliases}, key=len, reverse=True):
            for m in re.finditer(re.escape(name), view["text"]):
                ma, mb = a + m.start(), a + m.end()
                mid = _id("M", source_hash, ma, mb, name)
                packet["mentions"].append({"mention_id": mid, "source_span_id": sid,
                                           "start": ma, "end": mb, "raw": name, "person_id": target_id})
                packet["persons"][0]["mention_ids"].append(mid)
        for ca, cb in _clauses(view):
            clause = text_full[ca:cb]
            prior = bool(_PRIOR.search(clause) and re.search(r"处罚|拘留|罚款", clause))
            scene_kind = "prior_penalty" if prior else "gambling_activity" if _BEHAVIOR.search(clause) else "context"
            scene_id = _id("SC", source_hash, ca, cb, scene_kind)
            packet["scenes"].append({"scene_id": scene_id, "kind": scene_kind,
                                     "state": "provisional", "support_span_ids": [sid], "start": ca, "end": cb})
            matches = []
            for typ, pattern in (("amount", MONEY), ("count", COUNT), ("age", AGE),
                                 ("date", TIME), ("duration", DURATION)):
                for m in pattern.finditer(clause):
                    ma, mb = ca + m.start(), ca + m.end()
                    if any(ma < x[2] and x[1] < mb for x in matches):
                        continue
                    matches.append((typ, ma, mb, m.group()))
            matches.sort(key=lambda x: (x[1], x[2]))
            last_amount_end = ca
            for typ, ma, mb, raw in matches:
                local = text_full[last_amount_end:ma] if typ == "amount" else text_full[ca:ma]
                if typ == "amount":
                    last_amount_end = mb
                actor, actor_status = _actor(local, target, aliases)
                role = _amount_role(local) if typ == "amount" else None
                unit = "CNY" if typ == "amount" else (re.search(r"人|次|场|台|张|岁", raw).group()
                                                        if typ in {"count", "age"} and re.search(r"人|次|场|台|张|岁", raw)
                                                        else "calendar" if typ == "date" else "days")
                if typ == "age":
                    role = "age"
                elif typ == "count":
                    if unit in {"台", "张"}:
                        role = "equipment_count"
                    elif unit == "人":
                        role = "cumulative_participants" if "累计" in clause else "participant_count" if re.search(r"参赌|赌博", clause) else None
                    elif unit in {"次", "场"}:
                        role = "times" if _BEHAVIOR.search(clause) else None
                elif typ == "date":
                    role = "prior_penalty" if prior else "birth" if re.search(r"出生|生于", clause) else "behavior_date" if _BEHAVIOR.search(clause) else None
                elif typ == "duration":
                    role = "duration_days" if _BEHAVIOR.search(clause) else None
                qid = _id("Q", source_hash, ma, mb, typ)
                candidate = {"candidate_id": qid, "type": typ, "source_span_id": sid,
                             "start": ma, "end": mb, "raw": raw, "unit": unit,
                             "normalizer_version": f"engine-e05/{schema_version}",
                             "scene_id": scene_id, "role_hint": role, "actor_hint": actor,
                             "actor_status": actor_status, "distribution": "each" if re.search(r"各|分别", local)
                             else "collective" if re.search(r"共|合计", local) else "unspecified"}
                candidate.update(_normalized(raw, typ))
                packet["quantities"].append(candidate)
                if typ == "amount":
                    eid = _id("EI", source_hash, ma, mb)
                    packet["economic_items"].append({"economic_item_id": eid, "kind_hint": role,
                                                     "identity_status": "provisional", "quantity_candidate_ids": [qid]})
                else:
                    eid = None
                cid = _id("C", source_hash, ca, cb, qid)
                polarity = "negative" if _NEGATION.search(local[-8:]) else "positive"
                packet["claims"].append({"claim_id": cid, "predicate_hint": role, "actor_hint": actor,
                                         "actor_status": actor_status, "scene_id": scene_id,
                                         "economic_item_id": eid, "quantity_ref_ids": [qid],
                                         "polarity": polarity, "assertion_source": view["type"],
                                         "source_span_ids": [sid], "state": "proposed"})
                if candidate["parse_status"] != "resolved":
                    packet["unresolved"].append({"candidate_id": qid, "reason": candidate["reason"]})
                if actor_status in {"joint", "unresolved"}:
                    packet["unresolved"].append({"candidate_id": qid, "reason": "subject_ambiguous"})
    if not packet["persons"][0]["mention_ids"]:
        raise ValueError("supply_target_not_visible")
    return packet


def prompt_catalog(packet: dict) -> list[dict]:
    """Compact candidate hints. The model still decides semantic relations."""
    return [{k: q.get(k) for k in ("candidate_id", "source_span_id", "start", "end", "raw",
                                   "type", "unit", "kind", "operator", "lower", "upper",
                                   "lower_inclusive", "upper_inclusive", "start_date", "end_date",
                                   "days", "role_hint", "actor_hint", "actor_status",
                                   "distribution", "scene_id", "parse_status")}
            for q in packet.get("quantities", [])]


def audit_elements(elements: dict, packet: dict) -> dict:
    """Reject provable numeric conflicts; never call a lexical proposal gold."""
    source = packet["source"]
    target_id = source["target_id"]
    candidates = packet.get("quantities", [])
    negative_ids = {qid for claim in packet.get("claims", []) if claim.get("polarity") == "negative"
                    for qid in claim.get("quantity_ref_ids", [])}
    result = {}
    for group, fields in elements.items():
        for name, item in fields.items():
            path = f"{group}.{name}"
            if item.get("status") == "未提及":
                result[path] = {"status": "unchecked", "reason": "absence_not_proven"}
                continue
            if path not in _AMOUNT_FIELD_ROLE and path not in _COUNT_FIELD_ROLE and path != "conduct.duration_days":
                result[path] = {"status": "unchecked", "reason": "non_numeric_semantics_not_audited"}
                continue
            evidence = item.get("evidence") or []
            located = [(ev.get("start"), ev.get("end")) for ev in evidence]
            refs = [q for q in candidates if any(type(a) is int and type(b) is int and
                                                  a <= q["start"] < q["end"] <= b for a, b in located)]
            if not refs:
                result[path] = {"status": "unverified", "reason": "candidate_missing_or_derived"}
                continue
            expected_role = _AMOUNT_FIELD_ROLE.get(path) or _COUNT_FIELD_ROLE.get(path) or "duration_days"
            compatible = [q for q in refs if q["role_hint"] in {expected_role, None}]
            if not compatible:
                definite_unit_conflict = (path in _COUNT_FIELD_ROLE and
                                          all(q["type"] in {"count", "age"} and
                                              q["unit"] not in ({"岁"} if path == "person.age" else
                                                                 {"次", "场"} if path == "conduct.times" else {"人"})
                                              for q in refs))
                result[path] = {"status": "quarantined" if definite_unit_conflict else "unverified",
                                "reason": "unit_conflict" if definite_unit_conflict else "role_binding_ambiguous",
                                "candidate_ids": [q["candidate_id"] for q in refs]}
                continue
            value = item.get("value")
            matched = []
            for q in compatible:
                if q.get("parse_status") != "resolved":
                    continue
                projected = q.get("engine_projection") or {}
                try:
                    if path in _AMOUNT_FIELD_ROLE and isinstance(value, dict):
                        ok = (Decimal(str(value["min"])) == Decimal(str(projected["min"])) and
                              (value.get("max") is None and projected.get("max") is None or
                               value.get("max") is not None and projected.get("max") is not None and
                               Decimal(str(value["max"])) == Decimal(str(projected["max"]))))
                    elif path == "conduct.duration_days":
                        ok = Decimal(str(value)) == Decimal(str(projected["days"]))
                    else:
                        ok = type(value) is int and projected.get("exact") is True and value == projected["min"]
                except (KeyError, TypeError, ValueError, InvalidOperation):
                    ok = False
                if ok:
                    matched.append(q)
            if not matched:
                result[path] = {"status": "unverified", "reason": "value_requires_derivation_or_review",
                                "candidate_ids": [q["candidate_id"] for q in compatible]}
                continue
            if all(q["candidate_id"] in negative_ids for q in matched):
                result[path] = {"status": "quarantined", "reason": "explicit_negative_claim",
                                "candidate_ids": [q["candidate_id"] for q in matched]}
                continue
            subject_specific = (path in _AMOUNT_FIELD_ROLE and path != "amounts.onsite_stake_total"
                                or path in {"person.age", "conduct.times"})
            if subject_specific and all(q["actor_status"] == "other" for q in matched):
                result[path] = {"status": "quarantined", "reason": "explicit_other_subject",
                                "candidate_ids": [q["candidate_id"] for q in matched]}
                continue
            if any(q["actor_status"] in {"joint", "unresolved"} for q in matched):
                result[path] = {"status": "unverified", "reason": "relation_ambiguous",
                                "candidate_ids": [q["candidate_id"] for q in matched]}
                continue
            if path == "amounts.onsite_stake_total":
                # A scene amount needs independently established target membership.
                result[path] = {"status": "unverified", "reason": "scene_membership_unproven",
                                "candidate_ids": [q["candidate_id"] for q in matched]}
                continue
            result[path] = {"status": "candidate_supported", "reason": "lexical_proposal_only",
                            "candidate_ids": [q["candidate_id"] for q in matched],
                            "target_id": target_id}
    return {"version": VERSION, "field_disposition": result,
            "counts": {status: sum(v["status"] == status for v in result.values())
                       for status in ("candidate_supported", "unverified", "quarantined", "unchecked")}}

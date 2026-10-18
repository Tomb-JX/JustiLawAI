"""Source-grounded candidate graph. Lexical bindings are proposals, never gold.

Explicit subject/event/role edges make same-valued money in different clauses
distinguishable. Unsupported/pronominal/joint relationships remain unresolved.
"""
from __future__ import annotations

import re

from element_contract import digest, normalize_amount_e05, normalize_date_e05, normalize_duration_e05
from evidence_types import SourceSpan
from normalization import NUM, normalize_quantity, normalize_time

VERSION = "evidence-graph-2"
MONEY = re.compile(fr"(?:不超过|不低于|至少|不足|超过|约|近|逾)?{NUM}(?:(?:到|至|[-~～]){NUM})?[余多]?(?:元|块)(?:以上|以下|左右)?")
COUNT = re.compile(fr"(?:至少|超过|不足|至多)?{NUM}(?:(?:至|到){NUM})?[余多]?(?:名|个)?(?:人|次|场|台)")
TIME = re.compile(r"(?:\d{4}|[〇零一二三四五六七八九]{4})年(?:[\d一二三四五六七八九十]+月(?:[\d一二三四五六七八九十]+[日号])?)?(?:(?:至|到)[\d一二三四五六七八九十]+月)?|同年[\d一二三四五六七八九十]+月|去年[\d一二三四五六七八九十]+月|次日|翌日")
ROLE_PATTERNS = {
    "personal_stake": r"(?:本人|个人|携带|持有|投入|赌资|赌注|筹码)",
    "per_bet": r"每局|每注|单注|每把",
    "onsite_stake_total": r"现场.*(?:赌资|赌款)|赌资.*合计|查获.*赌资",
    "cumulative_stake": r"累计.*(?:赌资|赌款)|赌资.*累计",
    "commission": r"抽头|渔利|头钱|水钱|台费|场地费",
    "illegal_gain": r"违法所得",
    "fine": r"罚款",
}


def _e05_money(quote: str, ref) -> dict:
    """E-05 authoritative money normalization, output compatible with graph node format."""
    result = normalize_amount_e05(quote)
    if result is None:
        return {"raw": quote, "source_ref": ref.to_dict(), "normalizer": "e05-normalization-spec",
                "kind": "unknown", "resolution": "unresolved", "reason": "e05_parse_failed"}
    return {"raw": quote, "source_ref": ref.to_dict(), "normalizer": "e05-normalization-spec",
            "unit": "CNY",
            "kind": "exact" if result["min"] == result.get("max") else "lower_bound" if result.get("max") is None else "interval",
            "operator": "=" if result["min"] == result.get("max") else ">=" if result.get("max") is None else "~",
            "lower": str(result["min"]), "upper": str(result["max"]) if result.get("max") is not None else None,
            "lower_inclusive": True, "upper_inclusive": result.get("max") is not None,
            "resolution": "resolved", "e05": True}


def _e05_time(quote: str, ref) -> dict:
    """E-05 authoritative date normalization, output compatible with graph node format."""
    result = normalize_date_e05(quote)
    if result is None:
        # Try duration
        dur = normalize_duration_e05(quote)
        if dur is not None:
            return {"raw": quote, "source_ref": ref.to_dict(), "normalizer": "e05-normalization-spec",
                    "kind": "duration", "resolution": "resolved", "duration": dur, "e05": True}
        return {"raw": quote, "source_ref": ref.to_dict(), "normalizer": "e05-normalization-spec",
                "kind": "unknown", "resolution": "unresolved", "reason": "e05_parse_failed"}
    d, status = result
    return {"raw": quote, "source_ref": ref.to_dict(), "normalizer": "e05-normalization-spec",
            "kind": "calendar_range", "resolution": "resolved",
            "precision": "day" if status == "明确" else "month",
            "start_date": d.isoformat(), "end_date": d.isoformat(),
            "e05": True}


def build_graph(original: str, views: list[dict], target: str, aliases=(), *, event_id=None):
    if not target or target not in original or any(not a or a not in original for a in aliases):
        raise ValueError("graph_target_not_source_grounded")
    nodes = []
    seen = set()
    for view in views:
        SourceSpan.from_text(original, view['start'], view['end'])
        if original[view["start"]:view["end"]] != view["text"]:
            raise ValueError("graph_view_source_mismatch")
        bounds, start = [], 0
        for delimiter in re.finditer(r'[。；;\n]|(?<!\d)[，,]|[，,](?!\d)', view['text']):
            bounds.append((start, delimiter.end()))
            start = delimiter.end()
        if start < len(view['text']):
            bounds.append((start, len(view['text'])))
        for cstart, cend in bounds:
            ca, cb = view["start"] + cstart, view["start"] + cend
            quote = original[ca:cb]
            mentions = []
            for name in sorted(set((target, *aliases)), key=len, reverse=True):
                for found in re.finditer(re.escape(name), quote):
                    mentions.append(SourceSpan.from_text(original, ca + found.start(), ca + found.end()).to_dict())
            event_kind = ("review" if view.get("type") == "review" else "penalty" if view.get("type") == "decision"
                          else "prior_penalty" if re.search(r"曾|前次|上次|此前", quote) and re.search(r"处罚|拘留|罚款", quote)
                          else "behavior")
            ev = event_id or "E-" + digest({"source": SourceSpan.from_text(original, ca, cb).to_dict(), "kind": event_kind})[:20]
            joint = bool(re.search(r"分别|各自|各有|与|和|伙同|、|等[\d一二三四五六七八九十]+人", quote))
            for kind, pattern in (("money", MONEY), ("count", COUNT), ("time", TIME)):
                for match in pattern.finditer(quote):
                    a, b = ca + match.start(), ca + match.end()
                    if (kind, a, b) in seen:
                        continue
                    seen.add((kind, a, b))
                    ref = SourceSpan.from_text(original, a, b)
                    before = quote[:match.start()]
                    # Select the closest explicit role keyword to THIS amount.
                    role_hits = [(m.end(), role) for role, pat in ROLE_PATTERNS.items()
                                 for m in re.finditer(pat, before)] if kind == "money" else []
                    roles = sorted({role for pos, role in role_hits if pos == max((x[0] for x in role_hits), default=-1)})
                    role = roles[0] if len(roles) == 1 else None
                    if role is None and kind == "money" and "personal_stake" in roles:
                        if re.search(r"(?:本人|个人|携带|持有|投入)[^，,。；;]{0,16}赌资?$", before):
                            role = "personal_stake"
                    if kind == "count":
                        role = ('cumulative_participants' if '累计' in quote else 'participant_count') if ref.quote.endswith('人') and re.search(r'参赌|赌博', quote) else 'times' if ref.quote.endswith(('次','场')) and re.search(r'赌博|参赌|提供条件', quote) else 'unclassified_count'
                    if kind == "time":
                        role = "birth" if re.search(r"出生|生于", quote) else "prior_penalty" if event_kind == "prior_penalty" else event_kind
                    binding = "unresolved"
                    if mentions and not joint and role:
                        binding = "lexical_candidate"
                    normalized = (_e05_time(ref.quote, ref) if kind == "time" else
                                  _e05_money(ref.quote, ref) if kind == "money" else
                                  normalize_quantity(ref.quote, ref, unit="count"))
                    nodes.append({"id": "V-" + digest({"kind": kind, "span": ref.to_dict(), "version": VERSION})[:20],
                                  "kind": kind, "source_ref": ref.to_dict(), "clause_ref": SourceSpan.from_text(original, ca, cb).to_dict(),
                                  "sentence_ref": view.get("id"), "target": target, "subject_refs": mentions,
                                  "event_id": ev, "event_kind": event_kind, "value_role": role,
                                  "binding": binding, "reason": "joint_or_indirect_subject" if joint or not mentions else "role_unresolved" if not role else None,
                                  "normalized": normalized, "semantic_approved": False})
            # Behavior node: capture clauses that mention the target (for evidence-aware binding)
            if target in quote:
                clause_key = ("behavior", ca, cb)
                if clause_key not in seen:
                    seen.add(clause_key)
                    ref = SourceSpan.from_text(original, ca, cb)
                    nodes.append({"id": "V-" + digest({"kind": "behavior", "span": ref.to_dict(), "version": VERSION})[:20],
                                  "kind": "behavior", "source_ref": ref.to_dict(), "clause_ref": ref.to_dict(),
                                  "sentence_ref": view.get("id"), "target": target, "subject_refs": mentions,
                                  "event_id": ev, "event_kind": event_kind, "value_role": None,
                                  "binding": "unresolved", "reason": None,
                                  "normalized": {"raw": quote, "source_ref": ref.to_dict(), "resolution": "resolved",
                                                 "kind": "behavior_clause", "e05": False}, "semantic_approved": False})
    return {"version": VERSION, "target": target, "nodes": nodes, "_original": original}


def classify_graph_bindings(graph: dict, *, aliases=()) -> dict:
    """Classify graph nodes with evidence-aware binding (3-step).

    Step 1: Field semantic lookup (FIELD_BINDING table)
    Step 2: Evidence subject detection (who is mentioned in quote)
    Step 3: Binding decision (field semantics + evidence content + section type)

    Engine defines semantics; postprocessing implements classification.
    """
    from element_contract import binding_rules
    br = binding_rules()
    field_binding = br.FIELD_BINDING
    target = graph.get("target", "")
    same_person = frozenset((target, *aliases))

    for node in graph.get("nodes", []):
        role = node.get("value_role")
        kind = node.get("kind", "")

        # Behavior nodes: use evidence-aware binding (no field lookup needed)
        if kind == "behavior":
            clause_ref = node.get("clause_ref") or {}
            clause_text = graph.get("_original", "")[clause_ref.get("start", 0):clause_ref.get("end", 0)]
            if not clause_text:
                clause_text = node.get("source_ref", {}).get("quote") or ""
            mentions_target = target in clause_text
            list_pattern = re.compile(
                rf"(?:[\u4e00-\u9fff*]{{1,4}}\s*[、和与，,]\s*)*{re.escape(target)}\s*[、和与，,]\s*[\u4e00-\u9fff*]{{1,4}}"
                rf"|[\u4e00-\u9fff*]{{1,4}}\s*[、和与，,]\s*{re.escape(target)}"
            )
            has_others = bool(list_pattern.search(clause_text))
            if has_others:
                node["binding"] = "needs_review"
                node["binding_reason"] = "multi-person behavior: target in list with others"
            elif mentions_target:
                node["binding"] = "target_specific"
                node["binding_reason"] = "behavior clause, only target mentioned"
            else:
                node["binding"] = "target_specific"
                node["binding_reason"] = "behavior clause, no explicit subject"
            continue

        # A scene word describes context, not the semantic role of each amount.
        # In particular, a nearby person's own stake must never become shared.
        if kind == "money":
            clause_ref = node.get("clause_ref") or {}
            clause_text = graph.get("_original", "")[clause_ref.get("start", 0):clause_ref.get("end", 0)]
            if not clause_text:
                clause_text = node.get("source_ref", {}).get("quote") or ""
            list_pattern = re.compile(
                rf"(?:[\u4e00-\u9fff*]{{1,4}}\s*[、和与，,]\s*)*{re.escape(target)}\s*[、和与，,]\s*[\u4e00-\u9fff*]{{1,4}}"
                rf"|[\u4e00-\u9fff*]{{1,4}}\s*[、和与，,]\s*{re.escape(target)}"
            )
            has_multi = bool(list_pattern.search(clause_text))
            if has_multi:
                node["binding"] = "needs_review"
                node["binding_reason"] = "multi-person evidence: target in list with others"
                continue

        if not role:
            node["binding"] = "needs_review"
            node["binding_reason"] = f"unclassified role: {role}"
            continue
        field = _role_to_field(role)
        if field is None:
            node["binding"] = "needs_review"
            node["binding_reason"] = f"no field mapping for role: {role}"
            continue

        # Step 1: Field semantic lookup
        binding_type = field_binding.get(field)
        if binding_type is None:
            node["binding"] = "needs_review"
            node["binding_reason"] = f"field not in FIELD_BINDING: {field}"
            continue

        if binding_type.value == "shared_fact":
            # SHARED fields: always shared, regardless of evidence
            node["binding"] = "shared_fact"
            node["binding_reason"] = f"scene-level field: {field}"
            continue

        # Step 2: Evidence subject detection
        # Use clause_ref (full clause) for person detection, not source_ref (matched pattern)
        clause_ref = node.get("clause_ref") or {}
        clause_text = graph.get("_original", "")[clause_ref.get("start", 0):clause_ref.get("end", 0)]
        if not clause_text:
            clause_text = node.get("source_ref", {}).get("quote") or ""

        # Detect if clause mentions target in a multi-person list context
        # Pattern: "甲、乙、丙" or "甲和乙" or "甲，乙" near target
        mentions_target_in_clause = target in clause_text
        mentions_others = False

        if mentions_target_in_clause:
            # Look for list patterns around target: names separated by 、和与,，
            list_pattern = re.compile(
                rf"(?:[\u4e00-\u9fff*]{{1,4}}\s*[、和与，,]\s*)*{re.escape(target)}\s*[、和与，,]\s*[\u4e00-\u9fff*]{{1,4}}"
                rf"|[\u4e00-\u9fff*]{{1,4}}\s*[、和与，,]\s*{re.escape(target)}"
            )
            for m in list_pattern.finditer(clause_text):
                segment = m.group()
                # Extract names from the segment
                names = re.findall(r"[\u4e00-\u9fff*]{1,4}", segment)
                for name in names:
                    if name != target and len(name) >= 2:
                        mentions_others = True
                        break
                if mentions_others:
                    break

        # Step 3: Binding decision
        if not mentions_target_in_clause:
            node["binding"] = "needs_review"
            node["binding_reason"] = "target-specific field without explicit target in clause"
        elif mentions_target_in_clause and not mentions_others:
            # Only target mentioned
            node["binding"] = "target_specific"
            node["binding_reason"] = f"only mentions {target}"
        elif mentions_others:
            # Others mentioned alongside target
            node["binding"] = "needs_review"
            node["binding_reason"] = "multi-person evidence: target in list with others"
        else:
            node["binding"] = "needs_review"
            node["binding_reason"] = "subject relationship unresolved"

    # Add summary
    from collections import Counter
    bindings = [n.get("binding", "needs_review") for n in graph.get("nodes", [])]
    counts = Counter(bindings)
    graph["binding_summary"] = {
        "total": len(bindings),
        "shared_fact": counts.get("shared_fact", 0),
        "target_specific": counts.get("target_specific", 0),
        "needs_review": counts.get("needs_review", 0),
    }
    return graph


def _role_to_field(role: str) -> str | None:
    """Map value_role to field path for binding classification."""
    mapping = {
        "personal_stake": "amounts.personal_stake",
        "per_bet": "amounts.per_bet",
        "onsite_stake_total": "amounts.onsite_stake_total",
        "cumulative_stake": "amounts.cumulative_stake",
        "commission": "amounts.commission",
        "illegal_gain": "amounts.illegal_gain",
        "fine": None,  # fine is penalty outcome, not a binding field
        "participant_count": "persons.participant_count",
        "cumulative_participants": "persons.cumulative_participants",
        "times": "conduct.times",
        "birth": "person.age",
        "prior_penalty": "circumstances.last_prior_penalty_date",
        "behavior": "conduct.behavior_type",
        "penalty": None,  # penalty is not a binding field
        "review": None,
        "unclassified_count": "persons.participant_count",  # conservative default
    }
    return mapping.get(role)


def resolve_binding(graph, candidate_id, *, target, event_id, value_role, evidence_spans):
    """Validate explicit edge selection, independently of numeric equality."""
    matches = [n for n in graph["nodes"] if n["id"] == candidate_id]
    if len(matches) != 1:
        raise ValueError("unknown_or_duplicate_candidate")
    node = matches[0]
    # A lexical candidate alone has no reviewed person/event semantics.
    if (node["target"] != target or node["event_id"] != event_id or node["value_role"] != value_role
            or node["binding"] not in ("target_specific", "shared_fact")):
        raise ValueError("subject_event_role_mismatch")
    ref = node["source_ref"]
    if not any(a <= ref["start"] < ref["end"] <= b for a, b in evidence_spans):
        raise ValueError("candidate_outside_cited_evidence")
    if value_role not in {"fine", "decision", "penalty"} and node["event_kind"] in {"penalty", "review"}:
        raise ValueError("observed_penalty_is_not_behavior_evidence")
    return node

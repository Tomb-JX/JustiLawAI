"""Offline contract for clause-level facts in a sentence-based S1 document.

Coordinates refer to cleaned_text, zero-based and half-open. This module does
not infer semantic boundaries; a model or reviewer must supply them.
"""

from __future__ import annotations

import re
from collections import Counter


_CLAUSE = re.compile(r"[^，,：:；;。！？\n]*(?:[，,：:；;。！？\n]|$)")
_MIXED_CUE = re.compile(r"(?:行为.{0,6}(?:构成|违反|属于|属)|情节(?:严重|较重|较轻)|现决定|决定给予)")
_FACT_CUE = re.compile(r"赌博|参赌|赌资|赌具|抽头|渔利|头钱|水钱|台费|赌场|赌机|棋牌|投案|自首|如实陈述|前科|曾受.{0,8}处罚|怀孕|孕妇|哺乳|未成年|查获|扣押|提供.{0,8}(?:场地|条件)")
_DATE_ONLY = re.compile(r"^\s*(?:\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-.]\d{1,2}[-.]\d{1,2})(?:\d{1,2}时(?:\d{1,2}分)?(?:许|左右)?)?[，,；;]?\s*$")
_HEADING = re.compile(r"^(?:现查明|经查明|主要违法事实|违法事实)[:：]$")
_GLUED_HEADING_DATE = re.compile(r"^(?:现查明|经查明)(?=\d{4}年)")
_TIME_CONTEXT_CUE = re.compile(r"(?:\d{4}|[〇零一二三四五六七八九十]{4})年|\d{1,2}月|\d{1,2}日|\d{1,2}时|当晚|当日|当天|次日|翌日|昨日|同年|当时")
FACT_ROLES = {"behavior_core", "other_case_fact", "context_time"}
FACT_VIEW_VERSION = "fact-view-v1"
FACT_CANDIDATE_VERSION = "fact-candidates-v2"


def clause_table(cleaned_text: str, sentences: list[list[int]]) -> list[dict]:
    """Build stable reference IDs; punctuation is included in each source span."""
    clauses = []
    for sentence_id, (left, right) in enumerate(sentences, 1):
        for match in _CLAUSE.finditer(cleaned_text[left:right]):
            value = match.group(0)
            if value.strip():
                clauses.append({"id": len(clauses) + 1, "sentence": sentence_id,
                                "start": left + match.start(), "end": left + match.end(),
                                "text": value})
    return clauses


def candidate_fact_clauses(cleaned_text: str, sentences: list[list[int]], *, version: str = "v1") -> list[dict]:
    """High-recall prompt candidates; a cue alone never assigns a facts label."""
    if version not in {"v1", "v2"}:
        raise ValueError("unsupported_fact_candidate_version")
    clauses = clause_table(cleaned_text, sentences)
    counts = Counter(c["sentence"] for c in clauses)
    candidates = {i for i, (a, b) in enumerate(sentences, 1)
                  if _MIXED_CUE.search(cleaned_text[a:b]) and counts[i] >= 2}
    if version == "v2":
        # Include intact fact sentences misplaced in reasoning/evidence by S1.
        # These are only review candidates; selection still belongs to the model.
        candidates.update(i for i, (a, b) in enumerate(sentences, 1)
                          if _FACT_CUE.search(cleaned_text[a:b]))
    return [c for c in clauses if c["sentence"] in candidates]


def resolve_fact_clause_ids(cleaned_text: str, sentences: list[list[int]],
                            clauses: list[dict], selected_ids: list[int]) -> list[dict]:
    """Resolve model/reviewer-selected IDs; reject guesses, duplicates and order changes."""
    if not isinstance(selected_ids, list) or any(type(x) is not int for x in selected_ids):
        raise ValueError("fact_clause_ids must be an integer array")
    if selected_ids != sorted(set(selected_ids)):
        raise ValueError("fact_clause_ids must be unique and ordered")
    by_id = {clause["id"]: clause for clause in clauses}
    if any(clause_id not in by_id for clause_id in selected_ids):
        raise ValueError("unknown fact clause ID")
    spans = [{"sentence": by_id[i]["sentence"], "start": by_id[i]["start"],
              "end": by_id[i]["end"], "text": by_id[i]["text"]} for i in selected_ids]
    if validate_fact_spans(cleaned_text, sentences, spans):
        raise ValueError("invalid source span")
    return spans


def validate_fact_spans(cleaned_text: str, sentences: list[list[int]], spans: list[dict]) -> list[str]:
    errors = []
    if not isinstance(spans, list):
        return ["facts_spans must be an array"]
    previous_end = -1
    for idx, item in enumerate(spans):
        if not isinstance(item, dict):
            errors.append(f"span {idx}: must be an object")
            continue
        sentence = item.get("sentence")
        start, end, quote = item.get("start"), item.get("end"), item.get("text")
        if type(sentence) is not int or not 1 <= sentence <= len(sentences):
            errors.append(f"span {idx}: invalid sentence")
            continue
        left, right = sentences[sentence - 1]
        if type(start) is not int or type(end) is not int or not left <= start < end <= right:
            errors.append(f"span {idx}: offset outside sentence")
            continue
        if start < previous_end:
            errors.append(f"span {idx}: overlap or wrong order")
        previous_end = end
        if not isinstance(quote, str) or cleaned_text[start:end] != quote:
            errors.append(f"span {idx}: text does not match source")
    return errors


def fact_text(cleaned_text: str, spans: list[dict]) -> str:
    return "".join(cleaned_text[item["start"]:item["end"]] for item in spans)


def effective_fact_spans(record: dict, output: dict) -> list[tuple[int, int, int, int]] | None:
    """Refine only candidate sentences; retain all other S1 facts zones unchanged.

    Returns None for historical outputs without the new key. The primary zones stay
    intact; this is a separate facts reference layer for S3 and later consumers.
    """
    view = fact_view(record, output)
    return None if view is None else [(v["start"], v["end"], v["start"], v["end"]) for v in view]


def fact_view(record: dict, output: dict) -> list[dict] | None:
    """Source-anchored facts projection shared by S3 and downstream consumers.

    A date-only clause immediately before a selected behavior clause is context,
    not an independent assertion. Mixed masked account/date clauses stay excluded.
    """
    selected = output.get("fact_clause_ids")
    if selected is None:
        return None
    cleaned = record.get("cleaned_text") or ""
    sentences = record.get("sentences") or []
    version = output.get("fact_candidate_version", "v1")
    candidates = candidate_fact_clauses(cleaned, sentences, version=version)
    candidate_sentences = {c["sentence"] for c in candidates}
    resolve_fact_clause_ids(cleaned, sentences, candidates, selected)
    declared_roles = output.get("fact_clause_roles")
    if declared_roles is not None:
        if (not isinstance(declared_roles, dict) or set(declared_roles) != {str(cid) for cid in selected}
                or any(value not in FACT_ROLES for value in declared_roles.values())):
            raise ValueError("invalid_fact_clause_roles")
    by_id = {c["id"]: c for c in candidates}
    chosen = set(selected)
    context = set()
    for cid in selected:
        previous = by_id.get(cid - 1)
        current = by_id[cid]
        if (previous and previous["sentence"] == current["sentence"]
                and _DATE_ONLY.fullmatch(previous["text"]) and cid - 1 not in chosen):
            context.add(cid - 1)
    view = []
    for zone in output.get("zones") or []:
        if zone.get("type") != "facts":
            continue
        for sentence_id in range(zone["from"], zone["to"] + 1):
            if sentence_id not in candidate_sentences:
                start, end = sentences[sentence_id - 1]
                view.append({"sentence": sentence_id, "start": start, "end": end,
                             "text": cleaned[start:end], "role": "legacy_sentence", "source": "zone"})
    for clause in candidates:
        cid = clause["id"]
        if cid not in chosen and cid not in context:
            continue
        if _HEADING.fullmatch(clause["text"].strip()):
            if declared_roles is not None:
                raise ValueError("heading_selected_as_fact")
            continue  # Structural heading is never projected as factual evidence.
        prefix = _GLUED_HEADING_DATE.match(clause["text"])
        start = clause["start"] + (prefix.end() if prefix else 0)
        value = cleaned[start:clause["end"]]
        if cid in context or _DATE_ONLY.fullmatch(value):
            role = "context_time"
        else:
            role = declared_roles[str(cid)] if declared_roles is not None else "narrative_fact"
        if declared_roles is not None and cid in chosen:
            declared = declared_roles[str(cid)]
            if declared == "context_time" and not _TIME_CONTEXT_CUE.search(value):
                raise ValueError("context_time_without_date")
            if declared == "behavior_core" and _DATE_ONLY.fullmatch(value):
                raise ValueError("date_only_as_behavior_core")
        view.append({"sentence": clause["sentence"], "start": start,
                     "end": clause["end"], "text": value,
                     "role": role, "source": "linked_date" if cid in context else "model", "clause_id": cid})
    return sorted(view, key=lambda item: (item["start"], item["end"]))


def ambiguous_fact_context(record: dict, output: dict) -> list[int]:
    """Flag date/identifier mixtures next to selected facts for source review."""
    selected = output.get("fact_clause_ids")
    if selected is None:
        return []
    clauses = candidate_fact_clauses(record.get("cleaned_text") or "", record.get("sentences") or [],
                                     version=output.get("fact_candidate_version", "v1"))
    by_id = {c["id"]: c for c in clauses}
    result = []
    for cid in selected:
        previous, current = by_id.get(cid - 1), by_id.get(cid)
        if (previous and current and previous["sentence"] == current["sentence"]
                and re.search(r"\d{4}年\d{1,2}月\d{1,2}日", previous["text"])
                and not _DATE_ONLY.fullmatch(previous["text"]) and cid - 1 not in selected):
            result.append(cid - 1)
    return sorted(set(result))


def fact_zone_conflicts(record: dict, output: dict) -> list[int]:
    """Selected fact clauses located in a non-facts primary sentence zone."""
    selected = output.get("fact_clause_ids")
    if selected is None:
        return []
    clauses = {c["id"]: c for c in candidate_fact_clauses(record.get("cleaned_text") or "",
                                                          record.get("sentences") or [],
                                                          version=output.get("fact_candidate_version", "v1"))}
    fact_sentences = {sid for zone in output.get("zones") or [] if zone.get("type") == "facts"
                      for sid in range(zone["from"], zone["to"] + 1)}
    return [cid for cid in selected if cid in clauses and clauses[cid]["sentence"] not in fact_sentences]

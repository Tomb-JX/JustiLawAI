"""Offline contract for clause-level facts in a sentence-based S1 document.

Coordinates refer to cleaned_text, zero-based and half-open. This module does
not infer semantic boundaries; a model or reviewer must supply them.
"""

from __future__ import annotations

import re
from collections import Counter


_CLAUSE = re.compile(r"[^，,：:；;。！？\n]*(?:[，,：:；;。！？\n]|$)")
_MIXED_CUE = re.compile(r"(?:行为.{0,6}(?:构成|违反|属于|属)|情节(?:严重|较重|较轻)|现决定|决定给予)")


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


def candidate_fact_clauses(cleaned_text: str, sentences: list[list[int]]) -> list[dict]:
    """High-recall prompt candidates; a cue alone never assigns a facts label."""
    clauses = clause_table(cleaned_text, sentences)
    counts = Counter(c["sentence"] for c in clauses)
    candidates = {i for i, (a, b) in enumerate(sentences, 1)
                  if _MIXED_CUE.search(cleaned_text[a:b]) and counts[i] >= 2}
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
    selected = output.get("fact_clause_ids")
    if selected is None:
        return None
    cleaned = record.get("cleaned_text") or ""
    sentences = record.get("sentences") or []
    candidates = candidate_fact_clauses(cleaned, sentences)
    candidate_sentences = {c["sentence"] for c in candidates}
    picked = resolve_fact_clause_ids(cleaned, sentences, candidates, selected)
    spans = []
    for zone in output.get("zones") or []:
        if zone.get("type") != "facts":
            continue
        for sentence_id in range(zone["from"], zone["to"] + 1):
            if sentence_id not in candidate_sentences:
                start, end = sentences[sentence_id - 1]
                spans.append((start, end, start, end))
    spans.extend((item["start"], item["end"], item["start"], item["end"]) for item in picked)
    return sorted(spans)

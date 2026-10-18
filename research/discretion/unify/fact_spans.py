"""Offline contract for clause-level facts in a sentence-based S1 document.

Coordinates refer to cleaned_text, zero-based and half-open. This module does
not infer semantic boundaries; a model or reviewer must supply them.
"""

from __future__ import annotations


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

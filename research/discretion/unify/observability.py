"""36-field diagnostics, explicitly distinct from source truth and accuracy."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

VERSION = "field-observability-1"
EXECUTION_FAILURES = {"invalid", "transport_failed", "unresolved", "not_available"}
REVIEW_REASONS = {"source_absent", "source_masked", "input_omitted", "ambiguous", "parser_failed", "unresolved"}


def diagnose(record, graph, catalog, *, execution="not_available", review=None):
    inp = record.get("input") or {}
    view = "\n".join(v["text"] for v in inp.get("views", [])) or "\n".join(
        inp.get(k) or "" for k in ("facts_text", "meta_text"))
    original = record.get("source_text") or record.get("text_full") or ""
    elements = record.get("elements") or {}
    result = []
    for path, rule in catalog["fields"].items():
        group, field = path.split(".")
        item = (elements.get(group) or {}).get(field)
        marker = rule.get("candidate_marker")
        full_hit = bool(marker and re.search(marker, original))
        view_hit = bool(marker and re.search(marker, view))
        review_item = (review or {}).get(path)
        reason = "unobserved"
        basis = "no_semantic_reference"
        if execution in EXECUTION_FAILURES:
            reason, basis = execution, "execution_state"
        elif not isinstance(item, dict) or set(item) != {"status", "value", "evidence"}:
            reason, basis = "invalid", "field_structure"
        elif item["status"] != "未提及":
            reason, basis = "value_reported", "model_candidate"
        elif full_hit and not view_hit:
            reason, basis = "input_omitted_candidate", "lexical_recall"
        elif view_hit:
            reason, basis = "unresolved", "lexical_candidate_but_no_value"
        elif marker is None:
            reason, basis = "no_marker_coverage", "no_recall_rule"
        related = [n for n in graph.get("nodes", []) if n.get("value_role") == field]
        if execution == "valid" and related and all(n["normalized"]["resolution"] != "resolved" for n in related):
            reason, basis = "parser_failed", "normalizer_diagnostic"
        if review_item:
            if (review_item.get("reason") not in REVIEW_REASONS or not review_item.get("reviewer")
                    or not review_item.get("reference_hash")):
                raise ValueError("invalid_observability_review")
            reason, basis = review_item["reason"], "independent_review"
        result.append({"path": path, "key_field": rule["key_field"], "execution": execution,
                       "content_status": item.get("status") if isinstance(item, dict) else None,
                       "reason": reason, "basis": basis, "source_marker_hit": full_hit,
                       "input_marker_hit": view_hit, "has_marker_rule": marker is not None})
    return result


def summarize(rows, catalog):
    groups = defaultdict(lambda: defaultdict(Counter))
    count = 0
    for row in rows:
        count += 1
        dimension = (row.get("source", "unknown"), row.get("form", "unknown"))
        for field in row["fields"]:
            counts = groups[dimension][field["path"]]
            counts["N"] += 1
            counts["reason:" + field["reason"]] += 1
            counts["source_marker_hit"] += field["source_marker_hit"]
            counts["input_marker_hit"] += field["input_marker_hit"]
            if field["execution"] == "valid":
                counts["valid_candidate_N"] += 1
                counts["unmentioned_in_valid_N"] += field["content_status"] == "未提及"
    dimensions = []
    for (source, form), fields in sorted(groups.items(), key=lambda x: str(x[0])):
        # Keep all 36 fields even where an empty stratum has no positive candidates.
        dimensions.append({"source": source, "form": form, "fields": {
            path: {**dict(fields[path]), "key_field": rule["key_field"],
                   "unmentioned_rate_in_valid": (fields[path]["unmentioned_in_valid_N"] / fields[path]["valid_candidate_N"]
                                                  if fields[path]["valid_candidate_N"] else None)}
            for path, rule in catalog["fields"].items()}})
    return {"version": VERSION, "records": count, "catalog_hash": catalog["hash"],
            "key_fields": catalog["key_fields"], "dimensions": dimensions,
            "field_accuracy": None, "reason": "no_independent_reference_labels"}

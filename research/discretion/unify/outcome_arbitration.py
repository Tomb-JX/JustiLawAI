"""Observation-preserving outcome adjudication, separate from normative diagnostics.

No penalty ceiling may select an extraction candidate. Every accepted decision
must carry its own permitted source references, including new referee values.
"""
from __future__ import annotations

import copy
from decimal import Decimal
import re

from element_contract import digest
from evidence_types import SourceSpan
from normalization import normalize_quantity, normalize_time
from evidence_graph import MONEY, TIME
from s1 import OUTCOME_TYPES

VERSION = "observed-outcome-2"
FIELD_SCHEMAS = {"fine": {"type": "number", "minimum": 0},
                 "detention_days": {"type": "integer", "minimum": 0},
                 "outcome.type": {"type": "string", "enum": OUTCOME_TYPES},
                 "not_executed": {"type": "string", "enum": ["是", "否"]},
                 "behavior_date": {"type": "string"}, "decision_date": {"type": "string"}}


def choice_schema(field):
    return {"type": "object", "required": ["adopt", "value", "evidence_ids", "reason"],
            "properties": {"adopt": {"enum": ["A", "B", "new", "unresolved"]},
                           "value": {"anyOf": [FIELD_SCHEMAS[field], {"type": "null"}]},
                           "evidence_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                           "reason": {"type": "string", "minLength": 1}}, "additionalProperties": False}


def messages(field, a, b, target, views):
    return [{"role": "system", "content": (
        "核对原文实际记载的历史观察值。不得用法律上限、现行规范或常识把观察值改成合法数字。"
        "只用允许句；区分本人/他人、原决定/复议、单项/合并执行。不能确定事件则 unresolved。"
        "adopt=A/B 也须给自己的原文引用，new 同样须证据。输出 JSON：" + __import__("json").dumps(choice_schema(field), ensure_ascii=False))},
            {"role": "user", "content": __import__("json").dumps({"field": field, "A": a, "B": b,
                 "target": target, "allowed_sentences": views}, ensure_ascii=False)}]


def validate_choice(payload, field, a, b, original, views, *, target):
    from jsonschema import Draft202012Validator
    if list(Draft202012Validator(choice_schema(field)).iter_errors(payload)):
        raise ValueError("invalid_outcome_choice_schema")
    if payload["adopt"] == "unresolved":
        if payload["value"] is not None or payload["evidence_ids"]:
            raise ValueError("unresolved_must_not_fabricate_value")
        return {**payload, "execution": "unresolved", "policy": VERSION}
    if payload["value"] is None or not payload["evidence_ids"]:
        raise ValueError("observed_value_requires_evidence")
    if payload["adopt"] in {"A", "B"} and digest(payload["value"]) != digest(a if payload["adopt"] == "A" else b):
        raise ValueError("adopted_value_mismatch")
    allowed = {v["id"]: v for v in views}
    spans = []
    for sid in payload["evidence_ids"]:
        if sid not in allowed:
            raise ValueError("outcome_reference_not_allowed")
        v = allowed[sid]
        span = SourceSpan.from_text(original, v["start"], v["end"])
        if span.quote != v["text"]:
            raise ValueError("outcome_reference_source_mismatch")
        spans.append(span)
    if not target or not any(target in span.quote for span in spans):
        raise ValueError("outcome_target_not_in_cited_evidence")
    # Conservative queue for multi-person or mixed original/review operative text.
    # Neither a common numeric value nor one target occurrence resolves these.
    if any(re.search(r"分别|各自|各有|[与和、].*(?:共|各|罚款|拘留)|原决定.*(?:变更|撤销)", s.quote) for s in spans):
        raise ValueError("ambiguous_outcome_subject_or_event")
    # Numeric support is local to the penalty clause, never another same-valued stake.
    supported = False
    for span in spans:
        if field == "fine":
            for m in re.finditer(r"罚款[^，。；;\n]*", span.quote):
                for value in MONEY.finditer(m.group()):
                    start = span.start + m.start() + value.start()
                    ref = SourceSpan.from_text(original, start, start + len(value.group()))
                    parsed = normalize_quantity(ref.quote, ref)
                    supported |= (parsed["kind"] == "exact" and parsed["resolution"] == "resolved"
                                  and Decimal(parsed["lower"]) == Decimal(str(payload["value"])))
        elif field == "detention_days":
            from normalization import NUM
            for m in re.finditer(fr"(?:行政)?拘留({NUM})[日天]", span.quote):
                ref = SourceSpan.from_text(original, span.start + m.start(1), span.start + m.end(1))
                # Count conversion uses a synthetic unit but keeps the real source ref.
                from normalization import _backend, _decimal
                got = _backend().money(ref.quote + "元")
                supported |= _decimal(got["num"]) == payload["value"]
        elif field in {"behavior_date", "decision_date"}:
            context = r'赌博|参赌|行为|参与' if field == 'behavior_date' else r'决定|作出|处罚'
            if not re.search(context, span.quote) or re.search(r'出生|生于|复议|撤销|维持', span.quote):
                continue
            for m in TIME.finditer(span.quote):
                ref = SourceSpan.from_text(original, span.start + m.start(), span.start + m.end())
                parsed = normalize_time(ref.quote, ref)
                supported |= parsed["resolution"] == "resolved" and parsed["precision"] == "day" and parsed["start_date"] == payload["value"]
        elif field == "outcome.type":
            value = payload["value"]
            fine = bool(re.search(r'罚款[^，。；]*元', span.quote)) and not re.search(r'不予|免予|无须|无需', span.quote)
            detention = bool(re.search(r'拘留[^，。；]*[日天]', span.quote)) and not re.search(r'不予|免予', span.quote)
            supported |= {'罚款': fine and not detention, '拘留': detention and not fine,
                          '拘留并处罚款': fine and detention,
                          '不予处罚': bool(re.search(r'不予(?:行政)?处罚', span.quote)),
                          '不构成违法': '不构成违法' in span.quote,
                          '警告': bool(re.search(r'(?:给予|予以)警告', span.quote)),
                          '移送刑事': bool(re.search(r'移送.*刑事', span.quote))}.get(value, False)
        else:
            supported |= bool(re.search(r"不[予]?执行|暂缓执行", span.quote)) if payload["value"] == "是" else "执行" in span.quote and not re.search(r"不[予]?执行|暂缓执行", span.quote)
    if not supported:
        raise ValueError("outcome_value_not_supported_by_own_evidence")
    return {**copy.deepcopy(payload), "evidence": [s.to_dict() for s in spans], "execution": "valid",
            "policy": VERSION, "binding_review_required": True, "release_approved": False}


def normative_diagnostic(field, value, *, edition=None):
    """Diagnostic only. Unknown applicable law produces no normative conclusion."""
    from s3 import PENALTY_CAPS
    caps = PENALTY_CAPS.get(edition)
    if not caps or field not in {"fine", "detention_days"}:
        return {"status": "needs_review", "reason": "applicable_norm_not_established", "observed_value": value}
    ceiling = caps["fine" if field == "fine" else "detention"]
    return {"status": "potential_norm_conflict" if value > ceiling else "within_single_item_cap_only",
            "observed_value": value, "ceiling": ceiling,
            "does_not_establish_applicability_or_legality": True}


def attach_commit(record_id, original, target, run):
    """Revalidate a new commit for parsed-2; historical observations stay separate."""
    import hashlib
    import json
    from cleanse import sentence_table
    from element_contract import implementation_snapshot
    if not re.fullmatch(r'[A-Za-z0-9_-]+', record_id):
        raise ValueError('unsafe_outcome_record_id')
    path = run / f'record-{record_id}.json'
    if not path.exists():
        return None
    manifest = json.loads((run / 'manifest.json').read_text('utf-8'))
    commit = json.loads(path.read_text('utf-8'))
    views = [{'id': f'O{i}', 'start': a, 'end': b, 'text': original[a:b]}
             for i, (a, b) in enumerate(sentence_table(original), 1)]
    if (commit.get('id') != record_id or commit.get('policy') != VERSION
            or commit.get('plan_hash') != digest(manifest) or commit.get('view_hash') != digest(views)
            or manifest.get('implementation') != implementation_snapshot()
            or commit.get('source_sha256') != hashlib.sha256(original.encode()).hexdigest()):
        raise ValueError('outcome_commit_context_mismatch')
    if not commit['decisions'] or set(commit['decisions']) != set(commit['input_candidates']):
        raise ValueError('outcome_commit_candidates_mismatch')
    result = {}
    for field, decision in commit['decisions'].items():
        raw = {k: decision[k] for k in ('adopt', 'value', 'evidence_ids', 'reason')}
        candidates = commit['input_candidates'][field]
        result[field] = validate_choice(raw, field, candidates['a'], candidates['b'], original, views, target=target)
    return {'policy': VERSION, 'decisions': result,
            'status': 'candidate_validated' if all(d['execution']=='valid' for d in result.values()) else 'unresolved',
            'release_approved': False, 'requires_binding_review': True}

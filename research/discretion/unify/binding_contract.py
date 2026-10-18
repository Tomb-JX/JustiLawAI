"""Compile explicit candidate selections into field grounding under an engine-approved policy.

This adapter is available to teacher/student callers; it does not guess missing
subject/event edges or silently upgrade the current engine output format.
"""
from __future__ import annotations

from decimal import Decimal

from evidence_graph import resolve_binding
from normalization import project_quantity, project_time

VERSION = 'field-bindings-1'


def ground_fields(payload, selections, graph, *, target, policy=None, contract_hash=None):
    if policy and (not policy.get('approved_by') or not policy.get('version') or not contract_hash
                   or policy.get('contract_hash') != contract_hash):
        raise ValueError('binding_policy_not_approved_for_contract')
    result = {}
    for group, fields in payload.items():
        for name, item in fields.items():
            path = group + '.' + name
            if item['status'] == '未提及':
                continue
            if group != 'amounts' and path not in {'conduct.times','persons.participant_count',
                 'persons.cumulative_participants','circumstances.last_prior_penalty_date'}:
                continue
            selected = selections.get(path)
            if not selected:
                raise ValueError('binding_not_selected:' + path)
            role = 'prior_penalty' if path == 'circumstances.last_prior_penalty_date' else name
            node = resolve_binding(graph, selected['candidate_id'], target=target,
                event_id=selected['event_id'], value_role=role,
                evidence_spans=[(e['start'], e['end']) for e in item['evidence']])
            normalized = node['normalized']
            projected = (project_time(normalized, policy=(policy or {}).get('time')) if node['kind']=='time'
                         else project_quantity(normalized, policy=(policy or {}).get('quantity')))
            if projected['value'] is None:
                raise ValueError('normalization_not_projectable:' + path)
            a, b = item['value'], projected['value']
            matches = (all(Decimal(str(a[k]))==Decimal(str(b[k])) if a[k] is not None and b[k] is not None
                           else a[k] is b[k] for k in ('min','max')) if group=='amounts' else a==b)
            if not matches:
                raise ValueError('selected_candidate_value_mismatch:' + path)
            if projected['losses'] and not (policy or {}).get('approved_by'):
                raise ValueError('lossy_projection_requires_engine_policy:' + path)
            result[path] = {'candidate_id': node['id'], 'event_id': node['event_id'], 'value_role': role,
                            'source_ref': node['source_ref'], 'projection': projected,
                            'semantic_policy_approved': bool((policy or {}).get('approved_by'))}
    return {'version': VERSION, 'bindings': result}

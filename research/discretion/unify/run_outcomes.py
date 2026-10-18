"""Observation-preserving referee. Default is offline planning, one request per record."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path

from arbitrate import check_isolation
from budget_scope import from_order
from cleanse import sentence_table
from durable_calls import DurableCalls, read_rows
from element_contract import digest, implementation_snapshot
from outcome_arbitration import VERSION, choice_schema, messages, validate_choice
from progress import load_prices
from provider_contract import freeze_execution
from s1 import data_root, load_config


def prepare(batch, divergences):
    rows = read_rows(batch)
    records = {r['id']: r for r in rows}
    if len(records) != len(rows):
        raise ValueError('duplicate_source_id')
    grouped = {}
    with divergences.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            item = {'field': row['field'], 'a': json.loads(row['s1']), 'b': json.loads(row['anchor'])}
            choice_schema(item['field'])
            grouped.setdefault(row['id'], []).append(item)
    tasks = []
    for rid, differences in grouped.items():
        if len({d['field'] for d in differences}) != len(differences):
            raise ValueError('duplicate_record_field_divergence')
        record = records[rid]
        original, target = record['text_full'], record.get('subject_mention') or ''
        if not target or target not in original:
            continue
        views = [{'id': f'O{i}', 'start': a, 'end': b, 'text': original[a:b]}
                 for i, (a, b) in enumerate(sentence_table(original), 1)]
        schema = {'type': 'object', 'properties': {d['field']: choice_schema(d['field']) for d in differences},
                  'required': [d['field'] for d in differences], 'additionalProperties': False}
        d = differences[0]
        base = messages(d['field'], d['a'], d['b'], target, views)[0]['content'].split('输出 JSON：')[0]
        msgs = [{'role': 'system', 'content': base + '全部争议字段 JSON：' + json.dumps(schema, ensure_ascii=False)},
                {'role': 'user', 'content': json.dumps({'target': target, 'allowed_sentences': views,
                 'differences': differences}, ensure_ascii=False)}]
        tasks.append((rid, record, views, differences, schema, msgs))
    return tasks


def compile_result(payload, record, views, differences, schema):
    from jsonschema import Draft202012Validator
    if list(Draft202012Validator(schema).iter_errors(payload)):
        raise ValueError('invalid_outcome_record_schema')
    return {d['field']: validate_choice(payload[d['field']], d['field'], d['a'], d['b'],
            record['text_full'], views, target=record['subject_mention']) for d in differences}


def main():
    __import__('sys').stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('batch', 'run', 'divergences', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--ids', type=Path)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--order', type=Path)
    a = p.parse_args()
    if not a.out.resolve().is_relative_to((data_root() / 's1_runs').resolve()) or a.out.resolve() == a.run.resolve():
        p.error('只写新的 $DATA/s1_runs 子目录')
    tasks = prepare(a.batch, a.divergences)
    if a.ids:
        ids = json.loads(a.ids.read_text('utf-8'))
        lookup = {t[0]: t for t in tasks}
        if len(ids) != len(set(ids)) or set(ids) - lookup.keys():
            p.error('ID 不唯一或不在合格分歧任务中')
        tasks = [lookup[rid] for rid in ids]
    snapshot = implementation_snapshot()
    frozen = {'version': VERSION, 'implementation': snapshot,
              'source_hashes': {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in (a.batch, a.divergences, a.run / 'outputs.jsonl')},
              'ids': [t[0] for t in tasks], 'requests': {t[0]: digest(t[-1]) for t in tasks}}
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = a.out / 'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text('utf-8')) != frozen:
        p.error('批次冻结不匹配，须换新目录')
    if not manifest.exists():
        manifest.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    if not a.execute:
        print(json.dumps({'records': len(tasks), 'plan_hash': digest(frozen), 'executed': False}))
        return
    if not a.order:
        p.error('默认不调用；须提供复核工单')
    order = json.loads(a.order.read_text('utf-8'))
    if (order.get('plan_hash') != digest(frozen) or order.get('stage') != 'smoke12'
            or order.get('policy_ack') != VERSION or order.get('free_replay_pass') is not True
            or not all(order.get(k) for k in ('review_record', 'executor_review', 'engine_ack'))
            or len(tasks) > 12 or not 0 < order.get('cap', 0) <= 4 or not 0 < order.get('max_calls', 0) <= 252):
        p.error('观察值策略未会签，或小批工单/预算不符')
    providers, _, _ = load_config()
    check_isolation(providers[order['provider']])
    prices = load_prices(data_root() / 'config/s1_prices.json')
    freeze_execution(a.out, order, providers, prices)
    calls = DurableCalls(a.out, providers, prices=prices, cap=order['cap'], max_calls=order['max_calls'],
                         max_input_bytes=order['max_input_bytes'], execute=True, budget_scope=from_order(order, data_root()))
    lock = a.out / 'RUNNING.lock'
    with lock.open('x') as f:
        f.write(str(os.getpid()))
    try:
        for rid, record, views, differences, schema, msgs in tasks:
            if snapshot != implementation_snapshot():
                raise RuntimeError('implementation_changed')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', rid):
                raise ValueError('unsafe_record_id')
            def valid(payload):
                return compile_result(payload, record, views, differences, schema)
            payload = calls.call(order['provider'], msgs, context={'id': rid, 'plan': digest(frozen)}, validator=valid)
            if snapshot != implementation_snapshot():
                raise RuntimeError('implementation_changed_during_call')
            result = {'id': rid, 'decisions': valid(payload), 'policy': VERSION,
                      'plan_hash': digest(frozen), 'source_sha256': hashlib.sha256(record['text_full'].encode()).hexdigest(),
                      'view_hash': digest(views), 'input_candidates': {d['field']: {'a': d['a'], 'b': d['b']} for d in differences},
                      'release_approved': False}
            result['status'] = 'valid' if all(d['execution']=='valid' for d in result['decisions'].values()) else 'unresolved'
            path = a.out / f'record-{rid}.json'
            if path.exists():
                if digest(json.loads(path.read_text('utf-8'))) != digest(result):
                    raise ValueError('existing_outcome_commit_mismatch')
            else:
                temp = path.with_suffix('.tmp')
                with temp.open('w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                temp.replace(path)
    finally:
        lock.unlink()


if __name__ == '__main__':
    main()

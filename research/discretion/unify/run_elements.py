"""Versioned element-reference runner. Default is offline planning, never paid calls.

Engine element semantics stay engine-owned. This wire version compiles sentence IDs
to its existing located contract. Old final300/elements is not a writable run target.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from element_contract import (engine_contract, contract_snapshot, digest, messages,
                              compile_references, merge_valid, validate_located, WIRE_VERSION)
from locate import OffsetIndex
from durable_calls import DurableCalls, append, read_rows, check_models
from s1 import data_root, load_config
from progress import load_prices
from cleanse import replay_edits, sentence_table
from evidence_types import CleanSpan, SourceSpan
from provider_contract import freeze_execution
from budget_scope import from_order
from task_result import failure_record
from fact_spans import fact_view, FACT_VIEW_VERSION
from normalization import normalize_time

ENGINE = engine_contract()
FIELD_INFO, PROMPT_VERSION = ENGINE.FIELD_INFO, ENGINE.PROMPT_VERSION


def build_inputs(rec: dict, seg_out: dict, index: OffsetIndex) -> dict | None:
    """One projection from clean half-open intervals, with no deleted text restored."""
    target = (rec.get("subject_mention") or "").strip()
    zones = (seg_out or {}).get("zones") or rec.get("zones_det") or []
    sentences = rec.get("sentences") or []
    original = rec.get("_text_full") or ""
    if not target or not zones or not sentences or target not in original:
        return None
    if hashlib.sha256(original.encode("utf-8")).hexdigest() != rec["text_orig_sha256"]:
        raise ValueError("text_hash_mismatch")
    types = {}
    previous = 0
    for zone in zones:
        a, b = zone.get("from"), zone.get("to")
        if (type(a) is not int or type(b) is not int or a != previous + 1
                or not 1 <= a <= b <= len(sentences)
                or zone.get("type") not in {"facts", "meta", "evidence", "reasoning", "decision", "review"}):
            raise ValueError("invalid_zones")
        types.update({sid: zone["type"] for sid in range(a, b + 1)})
        previous = b
    if previous != len(sentences):
        raise ValueError("incomplete_zones")
    refined = fact_view(rec, seg_out or {})
    refined_by_sentence = {}
    if refined is not None:
        for item in refined:
            refined_by_sentence.setdefault(item["sentence"], []).append(item)
    first_f = (min(refined_by_sentence) if refined_by_sentence else len(sentences) + 1) if refined is not None else next(
        (sid for sid, typ in types.items() if typ == "facts"), len(sentences) + 1)
    view = []
    for sid, typ in types.items():
        has_refined_facts = refined is not None and sid in refined_by_sentence
        if not has_refined_facts and typ != "facts" and not (typ == "meta" and sid < first_f):
            continue
        segments = (refined_by_sentence.get(sid, []) if refined is not None and (has_refined_facts or typ == "facts")
                    else [{"start": sentences[sid - 1][0], "end": sentences[sid - 1][1], "role": "zone"}])
        segment_type = "facts" if has_refined_facts else typ
        for segment_number, segment in enumerate(segments, 1):
            projected = index.project_span(CleanSpan(segment["start"], segment["end"]), original)
            for part, span in enumerate(projected, 1):
                a, b = span.start, span.end
                text = original[a:b]
                if text.strip():
                    if segment_type == "meta":
                        from freeze_slice import leak_reasons
                        if leak_reasons(text):
                            continue
                    item = {"id": f"S{sid}.{segment_number}.{part}" if refined is not None else f"S{sid}.{part}",
                            "sentence_id": sid, "type": segment_type, "start": a, "end": b,
                            "text": text, **({"fact_role": segment["role"]} if refined is not None and segment_type == "facts" else {})}
                    if item.get("fact_role") == "context_time" and len(projected) == 1:
                        stripped = text.rstrip("，,；;。 \n")
                        if stripped:
                            ref = SourceSpan.from_text(original, a, a + len(stripped))
                            item["normalized_time"] = normalize_time(stripped, ref)
                    view.append(item)
    if not view:
        return None
    if target not in '\n'.join(s['text'] for s in view):
        return None
    aliases = (seg_out or {}).get("subject", {}).get("aliases") or []
    if not isinstance(aliases, list) or any(not isinstance(a, str) or a not in original for a in aliases):
        raise ValueError("invalid_alias")
    return {"target": target, "aliases": aliases, "sentence_view": view,
            "facts_text": "\n".join(s["text"] for s in view if s["type"] == "facts"),
            "meta_text": "\n".join(s["text"] for s in view if s["type"] == "meta"),
            "regions": [(s["start"], s["end"]) for s in view],
            "view_hash": digest(view), "fact_view_version": FACT_VIEW_VERSION if refined is not None else None,
            "source_sha256": rec["text_orig_sha256"]}


def locate_evidence(quote: str, text_full: str, regions=()):
    """Legacy replay ONLY: exact, uniquely located inside the allowed input view."""
    if not isinstance(quote, str) or not quote.strip():
        return None
    hits, start = [], 0
    while (pos := text_full.find(quote, start)) >= 0:
        end = pos + len(quote)
        if not regions or any(a <= pos < end <= b for a, b in regions):
            hits.append((pos, end))
        start = pos + 1
    return hits[0] if len(hits) == 1 else None


def _candidates(payload, text_full, tag="", regions=()):
    issues = ENGINE.validate_teacher_output(payload, evidence_text=text_full)
    if issues:
        raise ValueError("invalid_legacy:" + ";".join(f"{i.field}:{i.code}" for i in issues))
    out = copy.deepcopy(payload)
    for group in out.values():
        for field in group.values():
            for ev in field["evidence"]:
                found = locate_evidence(ev["quote"], text_full, regions)
                if found is None:
                    raise ValueError("legacy_evidence_not_allowed_or_ambiguous")
                ev["start"], ev["end"] = found
    validate_located(out, text_full, ENGINE, regions)
    return out


def merge_labels(a_payload, b_payload, adjud=None):
    """Compatibility name: reject unvalidated legacy merging rather than manufacture nulls."""
    raise RuntimeError("使用 merge_valid 并显式传原文与允许区间；旧无校验合并接口已停用")


def load_work(run: Path, unified: Path, parsed: Path):
    from s3 import run_checks, zone_spans
    records = {r["id"]: r for r in read_rows(unified)}
    originals = {r["id"]: r for r in read_rows(parsed)}
    edits = {r["id"]: r for r in read_rows(unified.with_name("edits.rle.jsonl"))}
    work, rejected = [], []
    for out in read_rows(run / "outputs.jsonl"):
        rid = out.get("id")
        if not out.get("ok"):
            rejected.append({"id": rid, "reason": "s1_failed"})
            continue
        try:
            rec = dict(records[rid])
            rec["_text_full"] = originals[rid]["text_full"]
            if (replay_edits(rec["_text_full"], edits[rid]) != rec["cleaned_text"]
                    or sentence_table(rec["cleaned_text"]) != rec["sentences"]):
                raise ValueError("input_or_sentence_table_replay_mismatch")
            index = OffsetIndex(edits[rid])
            checks = run_checks({"record": rec, "output": out["output"], "sentences": rec["sentences"],
                                 "spans": zone_spans(out["output"], rec["sentences"], index)})
            if any(check.severity == "error" for check in checks):
                raise ValueError("upstream_s3_error")
            inp = build_inputs(rec, out["output"], index)
            if inp is None:
                raise ValueError("missing_target_or_input")
            work.append((rid, rec, inp))
        except (ValueError, IndexError, KeyError) as exc:
            rejected.append({"id": rid, "reason": str(exc)[:200]})
    return work, rejected


def load_slice_work(source: Path):
    """Use the frozen development view directly; this is not an S3 certificate."""
    from freeze_slice import leak_reasons
    from evidence_types import SourceSpan
    manifest = json.loads(source.with_name('manifest.json').read_text('utf-8'))
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['artifact_hashes']['records.jsonl']:
        raise ValueError('development_slice_hash_mismatch')
    entries = {r['id']: r for r in manifest['entries']}
    rows = read_rows(source)
    if len({r['id'] for r in rows}) != len(rows) or {r['id'] for r in rows} != entries.keys():
        raise ValueError('development_slice_id_mismatch')
    work, rejected = [], []
    for row in rows:
        rid = row['id']
        try:
            original, inp = row['source_text'], row['input']
            target, views = inp['target'], inp['views']
            if (hashlib.sha256(original.encode()).hexdigest() != row['text_orig_sha256']
                    or row['view_hash'] != digest(views) or row['view_hash'] != entries[rid]['view_hash']):
                raise ValueError('development_slice_record_hash_mismatch')
            if not views or target not in '\n'.join(v['text'] for v in views):
                raise ValueError('development_slice_target_not_visible')
            allowed = []
            for i, v in enumerate(views, 1):
                ref = SourceSpan.from_text(original, v['start'], v['end'])
                if ref.quote != v['text'] or v['type'] not in {'facts','meta'} or leak_reasons(v['text']):
                    raise ValueError('development_slice_input_not_isolated')
                allowed.append({**v, 'id':f'D{i}.1', 'sentence_id':i})
            facts = '\n'.join(v['text'] for v in views if v['type']=='facts')
            meta = '\n'.join(v['text'] for v in views if v['type']=='meta')
            if facts != inp['facts_text'] or meta != inp['meta_text']:
                raise ValueError('development_slice_view_text_mismatch')
            compiled = {'target':target,'aliases':[],'facts_text':facts,'meta_text':meta,
                        'sentence_view':allowed,'regions':[(v['start'],v['end']) for v in allowed],
                        'view_hash':digest(allowed)}
            work.append((rid, {**row, '_text_full':original}, compiled))
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append({'id':rid,'reason':str(exc)})
    return work, rejected


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path)
    p.add_argument("--unified", type=Path)
    p.add_argument("--parsed", type=Path)
    p.add_argument('--slice', type=Path, help='frozen development records.jsonl; no extra S1 calls')
    p.add_argument("--out", type=Path, required=True, help="new $DATA/s1_runs directory")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--ids", type=Path, help="预冻结的分层 ID JSON 数组；不按完成顺序取烟测样本")
    p.add_argument("--execute", action="store_true", help="requires registered smoke order and finite cap")
    p.add_argument("--order", type=Path, help="frozen reviewed order JSON; never inferred from defaults")
    args = p.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to((data_root() / "s1_runs").resolve()) or (args.run and out == args.run.resolve()):
        p.error("只写新的 $DATA/s1_runs 子目录，不写旧 run")
    if args.slice:
        if any((args.run, args.unified, args.parsed)):
            p.error('--slice 与 --run/--unified/--parsed 二选一')
        work, rejected = load_slice_work(args.slice)
        sources = (args.slice, args.slice.with_name('manifest.json'))
    else:
        if not all((args.run, args.unified, args.parsed)):
            p.error('须提供 --slice 或完整网页 S1 三件来源')
        work, rejected = load_work(args.run, args.unified, args.parsed)
        sources = (args.run / 'outputs.jsonl', args.unified, args.parsed, args.unified.with_name('edits.rle.jsonl'))
    if args.ids:
        ids = json.loads(args.ids.read_text("utf-8"))
        by_id = {w[0]: w for w in work}
        if len(ids) != len(set(ids)) or set(ids) - set(by_id):
            p.error("所选 ID 重复或未通过输入/S3 资格")
        work = [by_id[rid] for rid in ids]
    if args.limit:
        work = work[:args.limit]
    snapshot = contract_snapshot(ENGINE)
    frozen = {"version": WIRE_VERSION, "contract": snapshot,
              'input_mode': 'development_slice_no_s3_certificate' if args.slice else 's1_s3_qualified',
              "ids": [w[0] for w in work], "views": {rid: inp["view_hash"] for rid, _, inp in work},
              "source_hashes": {str(f.resolve()): hashlib.sha256(f.read_bytes()).hexdigest()
                                for f in sources}}
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text("utf-8")) != frozen:
        p.error("run manifest 不匹配，换新批次目录")
    if not manifest.exists():
        manifest.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", "utf-8")
    plan = {"eligible": len(work), "rejected": rejected, "contract_hash": digest(snapshot),
            "execute": args.execute, "release_approved": False}
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False))
        return
    if not args.order:
        p.error("付费须提供预登记 --order；默认只离线规划")
    order = json.loads(args.order.read_text("utf-8"))
    if (order.get("contract_hash") != digest(snapshot) or order.get("ids") != frozen["ids"]
            or not order.get("review_record") or not order.get("executor_review")
            or not order.get("engine_ack") or order.get("free_replay_pass") is not True):
        p.error("工单未固定本批 ID/契约，或缺复核/知会/免费重放回执")
    if order.get("stage") == "smoke12":
        if len(work) > 12 or order.get("cap", 0) > 4:
            p.error("首段仅允许 ≤12 件 / ¥4")
    elif order.get("stage") == "spec36":
        prior = order.get("prior_stage_receipt")
        if not prior or not Path(prior).is_file():
            p.error("第二段须有首段验收回执")
        receipt = json.loads(Path(prior).read_text("utf-8"))
        if receipt.get("pass") is not True or receipt.get("contract_hash") != digest(snapshot):
            p.error("首段回执未通过或契约不一致")
    else:
        p.error("工单须明确 smoke12/spec36 分段")
    cap, maximum = order.get("cap", 0), order.get("max_calls", 0)
    if not 0 < cap <= 12 or not 0 < maximum <= 252 or len(work) > 36:
        p.error("本 runner 仅支持已评审的小批上界；全量须另审工单")
    providers, _, _ = load_config()
    names = order["providers"]
    check_models(*(providers[names[k]] for k in ("A", "B", "C")))
    prices = load_prices(data_root() / "config/s1_prices.json")
    freeze_execution(out, order, providers, prices)
    calls = DurableCalls(out, providers, prices=prices, budget_scope=from_order(order, data_root()),
                         cap=cap, max_calls=maximum, max_input_bytes=order["max_input_bytes"], execute=True)
    lock = out / "RUNNING.lock"
    with lock.open("x", encoding="ascii") as f:
        f.write(str(__import__("os").getpid()))
    try:
        for rid, rec, inp in work:
            try:
                if contract_snapshot(ENGINE) != snapshot:
                    raise RuntimeError("engine_contract_changed:中途不换契约")
                if not __import__("re").fullmatch(r"[A-Za-z0-9_-]+", rid):
                    raise ValueError("unsafe_record_id")
                context = {"id": rid, "view": inp["view_hash"], "contract": digest(snapshot),
                           "source": rec["text_orig_sha256"]}
                def valid(payload):
                    compile_references(payload, inp, rec["_text_full"], ENGINE)
                candidates = []
                for tag in ("A", "B"):
                    payload = calls.call(names[tag], messages(ENGINE, inp),
                                         context={**context, "tag": tag}, validator=valid)
                    candidates.append(compile_references(payload, inp, rec["_text_full"], ENGINE))
                merged, unresolved, diffs = merge_valid(*candidates, ENGINE, rec["_text_full"], inp["regions"])
                if unresolved:
                    payload = calls.call(names["C"], messages(ENGINE, inp, decisions=unresolved),
                                         context={**context, "tag": "C"}, validator=valid)
                    c = compile_references(payload, inp, rec["_text_full"], ENGINE)
                    merged, unresolved, diffs = merge_valid(*candidates, ENGINE, rec["_text_full"], inp["regions"], c)
                if contract_snapshot(ENGINE) != snapshot:
                    raise RuntimeError('contract_changed_during_call:保留 raw，不提交混合契约标签')
                result = {"id": rid, "status": "valid", "elements": merged,
                          "input": {"target": inp["target"], "facts_text": inp["facts_text"],
                                    "meta_text": inp["meta_text"], "text_full": rec["_text_full"],
                                    "text_orig_sha256": rec["text_orig_sha256"]},
                          "element_schema_version": ENGINE.SCHEMA_VERSION,
                          "element_prompt_version": ENGINE.PROMPT_VERSION,
                          "wire_version": WIRE_VERSION, "contract_hash": digest(snapshot),
                          "view_hash": inp["view_hash"], "label_provenance": "model-adjudicated",
                          "human_review": False, "release_approved": False}
                # Per-record immutable commit; resume does not duplicate candidate rows.
                dest = out / f"record-{rid}.json"
                if not dest.exists():
                    temp = dest.with_suffix(".tmp")
                    with temp.open("w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False)
                        f.flush()
                        __import__("os").fsync(f.fileno())
                    temp.replace(dest)
                elif digest(json.loads(dest.read_text("utf-8"))) != digest(result):
                    raise RuntimeError("existing_commit_mismatch:不覆盖既有记录")
                append(out / "diagnostics.jsonl", {"id": rid, "n_diffs": len(diffs), "status": "valid",
                       "difference_kinds": dict(__import__("collections").Counter(d["kind"] for d in diffs))})
            except Exception as exc:
                append(out / "diagnostics.jsonl", failure_record(rid, exc))
                # A smoke is fail-fast; never continue through a contract/authority/budget failure.
                raise
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()

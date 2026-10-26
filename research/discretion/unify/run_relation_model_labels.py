"""Source-bound, budgeted A/B model-draft relation annotation.

Uses S1/L5 configured providers; raw replies and paid-attempt receipts remain in
the private data directory. It never marks model output as human gold.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from audit_supply_replay import rows
from durable_calls import DurableCalls, append
from experiment_participant_list import candidate_lists
from progress import load_prices
from s1 import data_root, load_config
from supply_packet import build_packet

PROMPT_VERSION = "relation-edge-model-draft-1"
FIELDS = ("personal_stake", "onsite_stake_total", "participant_count", "age")
ROLES = {"personal_stake", "onsite_stake_total", "participant_count", "age", "birth_date",
         "behavior_date", "prior_penalty", "penalty_fine", "commission", "illegal_gain",
         "equipment_count", "other"}
OWNERS = {"target", "other", "shared_scene", "target_and_scene", "unknown"}

SYSTEM = """你是行政赌博事实的关系边标注员。只依据提供的 facts/meta 原文和目标人，不得补看处罚决定、推理或案外信息。输出单个 JSON 对象。

目标是为每个给定 Q 数值/日期候选判断角色、人物归属、事件归属，并为每个 LC 名单候选判断完整性和参与。候选值已由程序定位；你不重新写数值，也不得因同值就认定同一人物或事件。脱敏同名可能是不同人；“等人”不是完整名单。共同持有不等于各人分别持有；前科罚款不等于本次赌资；组织者、望风者、场地提供者不自动计入参赌人数。同一候选可以兼有个人和现场两个角色。证据不足填 uncertain。

JSON 结构：
{"events":[{"event_id":"E1","kind":"gambling|prior_penalty|seizure|other","support_span_ids":["V1"],"target_participates":"yes|no|uncertain"}],
 "candidate_edges":[{"candidate_id":"Q...","decision":"asserted|irrelevant|uncertain","roles":["personal_stake|onsite_stake_total|participant_count|age|birth_date|behavior_date|prior_penalty|penalty_fine|commission|illegal_gain|equipment_count|other"],"owner":"target|other|shared_scene|target_and_scene|unknown","event_id":"E1或null","support_span_ids":["V1"]}],
 "list_edges":[{"list_candidate_id":"LC...","complete":"yes|no|uncertain","distinct_people":"yes|no|uncertain","target_participates":"yes|no|uncertain","event_id":"E1或null"}],
 "fields":{"personal_stake":{"status":"selected|absent|uncertain","candidate_id":"Q...或null"},"onsite_stake_total":{"status":"selected|absent|uncertain","candidate_id":"Q...或null"},"participant_count":{"status":"selected|absent|uncertain","candidate_id":"Q...或LC...或null"},"age":{"status":"selected|absent|uncertain","candidate_id":"Q...或null","birth_candidate_id":"Q...或null","event_date_candidate_id":"Q...或null"}}}

必须对输入中的每个 Q 和 LC 恰好给一条对应记录；没有 LC 时 list_edges=[]。事件 ID 在本记录内自定，所有被引用的事件 ID 必须在 events 中。support_span_ids 只能引用输入的 V ID。字段 selected 必须引用输入的候选 ID；年龄可引用显式年龄 Q，或给出生/行为日期两个操作数。字段 absent 是原文确实没有足够证据，uncertain 是存在候选但无法确认。不要输出额外说明。"""


def prompt_for(record: dict, packet: dict, lists: list[dict]) -> str:
    view_ids = {v["span_id"]: f"V{i}" for i, v in enumerate(packet["visible_spans"], 1)}
    views = [{"id": view_ids[v["span_id"]], "zone": v["zone"], "text": v["quote"]}
             for v in packet["visible_spans"]]
    quantities = [{"candidate_id": q["candidate_id"], "type": q["type"], "raw": q["raw"],
                   "normalized": q.get("engine_projection"), "parse_status": q["parse_status"],
                   "view_id": view_ids[q["source_span_id"]]}
                  for q in packet["quantities"]]
    list_items = [{"list_candidate_id": l["candidate_id"], "view_id": view_ids[l["source_span_id"]],
                   "slots": [m["raw"] for m in l["mentions"]], "derived_count": l["value"],
                   "behavior_trigger": l["trigger"],
                   "masked_surface_collision": l["masked_surface_collision"]} for l in lists]
    return json.dumps({"target": record["target"], "aliases": record["aliases"],
                       "visible_views": views, "quantities": quantities,
                       "list_candidates": list_items}, ensure_ascii=False)


def normalize_unselected(payload):
    """Drop candidate ids on absent/uncertain fields; status is the decision, ids are noise.

    Mutates in place (the returned payload is what gets stored) and records each
    cleaned field so the cleanup stays visible in the label file.
    """
    fields = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(fields, dict):
        return payload
    cleaned = []
    for name, item in fields.items():
        if isinstance(item, dict) and item.get("status") in {"absent", "uncertain"}:
            for key in ("candidate_id", "birth_candidate_id", "event_date_candidate_id"):
                if item.get(key) is not None:
                    item[key] = None
                    cleaned.append(name + "." + key)
    if cleaned:
        payload["_normalized_unselected"] = cleaned
    return payload


def validate_payload(payload: dict, packet: dict, lists: list[dict]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload_not_object")
    views = {f"V{i}" for i, _ in enumerate(packet["visible_spans"], 1)}
    quantities = {q["candidate_id"]: q for q in packet["quantities"]}
    list_ids = {l["candidate_id"]: l for l in lists}
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 20:
        raise ValueError("invalid_events")
    event_ids = {e.get("event_id") for e in events if isinstance(e, dict)}
    if len(event_ids) != len(events) or None in event_ids:
        raise ValueError("duplicate_or_missing_event_id")
    for e in events:
        if e.get("kind") not in {"gambling", "prior_penalty", "seizure", "other"} or e.get(
                "target_participates") not in {"yes", "no", "uncertain"}:
            raise ValueError("invalid_event_state")
        if not isinstance(e.get("support_span_ids"), list) or not set(e["support_span_ids"]) <= views:
            raise ValueError("invalid_event_support")
    edges = payload.get("candidate_edges")
    if not isinstance(edges, list) or len(edges) != len(quantities) or {
            e.get("candidate_id") for e in edges if isinstance(e, dict)} != set(quantities):
        raise ValueError("candidate_edges_not_complete")
    for edge in edges:
        if edge.get("decision") not in {"asserted", "irrelevant", "uncertain"} or edge.get("owner") not in OWNERS:
            raise ValueError("invalid_candidate_edge_state")
        roles = edge.get("roles")
        if not isinstance(roles, list) or not set(roles) <= ROLES:
            raise ValueError("invalid_candidate_roles")
        if edge.get("event_id") is not None and edge["event_id"] not in event_ids:
            raise ValueError("candidate_unknown_event")
        if not isinstance(edge.get("support_span_ids"), list) or not set(edge["support_span_ids"]) <= views:
            raise ValueError("candidate_unknown_support")
    list_edges = payload.get("list_edges")
    if not isinstance(list_edges, list) or len(list_edges) != len(list_ids) or {
            e.get("list_candidate_id") for e in list_edges if isinstance(e, dict)} != set(list_ids):
        raise ValueError("list_edges_not_complete")
    for edge in list_edges:
        if any(edge.get(k) not in {"yes", "no", "uncertain"} for k in
               ("complete", "distinct_people", "target_participates")):
            raise ValueError("invalid_list_edge_state")
        if edge.get("event_id") is not None and edge["event_id"] not in event_ids:
            raise ValueError("list_unknown_event")
    fields = payload.get("fields")
    if not isinstance(fields, dict) or set(fields) != set(FIELDS):
        raise ValueError("field_keys_mismatch")
    for name, item in fields.items():
        if not isinstance(item, dict) or item.get("status") not in {"selected", "absent", "uncertain"}:
            raise ValueError("invalid_field_state")
        cid = item.get("candidate_id")
        if cid is not None and cid not in quantities and cid not in list_ids:
            raise ValueError("field_candidate_unknown")
        if item["status"] != "selected" and cid is not None:
            raise ValueError("unselected_field_has_candidate")
        if name in {"personal_stake", "onsite_stake_total"} and cid is not None and (
                cid not in quantities or quantities[cid]["type"] != "amount"):
            raise ValueError("amount_field_wrong_type")
        if name == "participant_count" and cid is not None and cid not in list_ids and quantities[cid]["type"] != "count":
            raise ValueError("count_field_wrong_type")
        if name == "age":
            birth, event = item.get("birth_candidate_id"), item.get("event_date_candidate_id")
            if birth is not None and (birth not in quantities or quantities[birth]["type"] != "date"):
                raise ValueError("birth_operand_invalid")
            if event is not None and (event not in quantities or quantities[event]["type"] != "date"):
                raise ValueError("event_operand_invalid")
            if item["status"] == "selected" and not (
                    cid in quantities and quantities[cid]["type"] == "age" or birth and event):
                raise ValueError("selected_age_without_operands")
        elif item["status"] == "selected" and cid is None:
            raise ValueError("selected_field_without_candidate")


def run(batch: Path, out: Path, providers: dict, *, limit: int, execute: bool,
        cap: float, max_calls: int, max_tokens: int,
        provider_names: tuple[str, ...] = ("bailian", "deepseek"), ids: set[str] | None = None,
        workers: int = 1, abandon_unknown: bool = False) -> dict:
    manifest = json.loads((batch / "MANIFEST.json").read_text("utf-8"))
    source = batch / "inputs.jsonl"
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["inputs_sha256"]:
        raise ValueError("batch_hash_mismatch")
    records = list(rows(source))
    if len(records) != manifest["selected"]:
        raise ValueError("batch_count_mismatch")
    if any(name not in providers for name in provider_names):
        raise ValueError("configured_annotation_provider_missing")
    for name in provider_names:
        providers[name].max_tokens = max_tokens
        providers[name].temperature = 0
        if providers[name].model.startswith("qwen"):
            # DashScope Qwen does not count thinking against max_tokens; bound it explicitly
            # so the reservation (max_tokens * output price) stays an upper bound.
            providers[name].extra_body = {"thinking_budget": max_tokens // 2}
    prices = load_prices(data_root() / "config/s1_prices.json")
    out.mkdir(parents=True, exist_ok=True)
    labels_dir = out / "labels"
    labels_dir.mkdir(exist_ok=True)
    call_dir = out / "calls"
    calls = DurableCalls(call_dir, providers, prices=prices, cap=cap, max_calls=max_calls,
                         max_input_bytes=35000, execute=execute)
    stats_abandoned = calls.abandon_unknown() if abandon_unknown else 0
    stats = {"records": len(records), "limit": limit, "processed": 0, "success": 0,
             "failed": 0, "existing": 0, "abandoned_attempts_closed": stats_abandoned,
             "workers": workers, "provider_success": {name: 0 for name in provider_names}}
    if ids is not None:
        records = [r for r in records if r["id"] in ids]
    selected = records[:limit] if limit else records
    lock = threading.Lock()
    stop = threading.Event()
    dead: set[str] = set()

    def label(record: dict, packet: dict, lists: list[dict], user: str, name: str) -> None:
        dest = labels_dir / f"{record['id']}-{name}.json"
        if stop.is_set() or name in dead:
            return
        try:
            payload = calls.call(name, [{"role": "system", "content": SYSTEM},
                                       {"role": "user", "content": user}],
                                 context={"id": record["id"], "source": record["source_sha256"],
                                          "view": record["view_hash"], "prompt": PROMPT_VERSION,
                                          "provider_tag": name},
                                 validator=lambda x: validate_payload(normalize_unselected(x), packet, lists),
                                 repairs=1)
            result = {"id": record["id"], "source_sha256": record["source_sha256"],
                      "view_hash": record["view_hash"], "split": record["split"],
                      "provider": name, "model": providers[name].model,
                      "prompt_version": PROMPT_VERSION, "label_provenance": "model_draft",
                      "human_review": False, "release_approved": False,
                      "annotation": payload}
            temp = dest.with_suffix(".tmp")
            with temp.open("w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            temp.replace(dest)
            with lock:
                append(out / "diagnostics.jsonl", {"id": record["id"], "provider": name,
                                                   "status": "ok", "n_candidates": len(packet["quantities"]),
                                                   "n_lists": len(lists)})
                stats["success"] += 1
                stats["provider_success"][name] += 1
        except Exception as exc:
            with lock:
                append(out / "diagnostics.jsonl", {"id": record["id"], "provider": name,
                                                   "status": "error", "error_type": type(exc).__name__,
                                                   "error": str(exc)[:180]})
                stats["failed"] += 1
            if "budget_stop" in str(exc):
                stop.set()
            elif "provider_disabled" in str(exc) or "HTTP 402" in str(exc):
                # A dead provider (e.g. out of balance) stops only its own jobs.
                with lock:
                    dead.add(name)

    jobs = []
    for record in selected:
        packet = build_packet(record["text_full"], record, record_id=record["id"])
        lists = candidate_lists(packet, record["target"], record["aliases"])
        stats["processed"] += 1
        for name in provider_names:
            dest = labels_dir / f"{record['id']}-{name}.json"
            if dest.exists():
                validate_payload(json.loads(dest.read_text("utf-8"))["annotation"], packet, lists)
                stats["existing"] += 1
            else:
                jobs.append((record, packet, lists, prompt_for(record, packet, lists), name))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(label, *job) for job in jobs]:
            future.result()
    stats["stopped_on_budget_or_provider"] = stop.is_set()
    stats["submitted_calls"] = calls.used_calls
    stats["reserved_yuan"] = round(calls.reserved, 4)
    return stats



def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("batch", "out"):
        ap.add_argument("--" + name, type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cap", type=float, default=15.0)
    ap.add_argument("--max-calls", type=int, default=400)
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--providers", default="bailian,deepseek")
    ap.add_argument("--ids", type=Path, default=None, help="one record id per line; blind re-vote subset")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--alias", action="append", default=[], help="alias=base:model, e.g. kimi=bailian:kimi-k3")
    ap.add_argument("--abandon-unknown", action="store_true",
                    help="book in-flight attempts of a killed run at full reservation, then resubmit")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if not args.execute:
        print(json.dumps({"execute": False, "batch": str(args.batch), "limit": args.limit,
                          "providers": args.providers.split(","), "cap": args.cap,
                          "max_calls": args.max_calls, "max_tokens": args.max_tokens}, ensure_ascii=False))
        return
    providers, _, _ = load_config()
    for spec in args.alias:
        # alias=base:model clones a configured endpoint/key with another hosted model.
        alias, rest = spec.split("=", 1)
        base, model = rest.split(":", 1)
        clone = copy.copy(providers[base])
        clone.name, clone.model = alias, model
        providers[alias] = clone
    result = run(args.batch, args.out, providers, limit=args.limit, execute=True,
                 cap=args.cap, max_calls=args.max_calls, max_tokens=args.max_tokens,
                 provider_names=tuple(args.providers.split(",")),
                 ids=set(args.ids.read_text("utf-8").split()) if args.ids else None,
                 workers=args.workers, abandon_unknown=args.abandon_unknown)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

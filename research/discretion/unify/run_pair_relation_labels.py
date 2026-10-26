"""Model-draft person–amount relation labels (data supply for pair classifiers).

New schema, separate from the field/edge drafts: for every resolved amount and
every proposed person of a record, the relation between them; whether the amount
is a shared scene total; whether each person is the target; and any holder the
person proposals missed. Raw replies and paid-attempt receipts stay private.
Labels are model drafts, never human gold.
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
from experiment_relation_edges import amounts_of
from ownership import person_mentions
from progress import load_prices
from s1 import data_root, load_config
from supply_packet import build_packet

PROMPT_VERSION = "pair-relation-model-draft-1"
RELATIONS = {"holds", "each_share", "gives", "receives", "none", "uncertain"}
TRI = {"yes", "no", "uncertain"}

SYSTEM = """你是行政赌博文书的“人物—金额”关系标注员。只依据给定 facts/meta 原文，不补看处罚结果或案外信息。输出单个 JSON 对象。

金额候选（Q）与人物提案（P）已由程序给出；你不改写数值，只判断关系。每个 Q 对每个 P 给一个 relation：
- holds：该人持有、投入、携带、下注或赢得这笔钱（钱属于他/她）；
- each_share：这笔钱是“每人各/分别/均”的人均数额，该人也有一份；
- gives：该人是付出方或来源方（转出、输给他人、被骗、被收取、交给庄家）；
- receives：该人是收取方或获利方（收取投注、抽头、接受转账、骗得）；
- none：与该人无关；uncertain：证据不足。
scene_total：这笔钱是否为整个赌博现场/全体参与者的合计或现场无主赌资（yes/no/uncertain）。同一笔钱可以既是现场合计又与某人 holds（如“现场赌资共500元，均为张三持有”）。
is_target：每个 P 是否就是目标人（申请人、违法行为人等称呼可能指目标；表面相同的脱敏名可能是不同的人，无法判断填 uncertain）。
unlisted_holders：若某笔钱的持有人/收取人不在 P 列表中，按原文逐字写出其称呼；否则为空数组。

JSON 结构：
{"persons":[{"person_id":"P1","is_target":"yes|no|uncertain"}],
 "amounts":[{"candidate_id":"Q...","scene_total":"yes|no|uncertain","links":[{"person_id":"P1","relation":"holds|each_share|gives|receives|none|uncertain"}],"unlisted_holders":["原文称呼"]}]}
必须对每个 P 恰好一条 persons 记录；对每个 Q 恰好一条 amounts 记录，且其 links 覆盖全部 P。不要输出额外说明。"""


def persons_of(packet: dict, record: dict) -> list[dict]:
    """Distinct person proposals (same surface merged); target mentions first as P1."""
    groups: dict[str, dict] = {}
    for m in person_mentions(packet, record):
        key = "〈目标〉" if m["kind"] == "target" else m["raw"]
        g = groups.setdefault(key, {"surface": record["target"] if m["kind"] == "target" else m["raw"],
                                    "kind": m["kind"], "mentions": []})
        g["mentions"].append([m["start"], m["end"]])
    ordered = sorted(groups.values(), key=lambda g: (g["kind"] != "target", g["mentions"][0][0]))
    return [{"person_id": f"P{i}", **g} for i, g in enumerate(ordered, 1)]


def prompt_for(record: dict, packet: dict, persons: list[dict]) -> str:
    view_ids = {v["span_id"]: f"V{i}" for i, v in enumerate(packet["visible_spans"], 1)}
    return json.dumps({
        "target": record["target"], "aliases": record["aliases"],
        "visible_views": [{"id": view_ids[v["span_id"]], "zone": v["zone"], "text": v["quote"]}
                          for v in packet["visible_spans"]],
        "amounts": [{"candidate_id": q["candidate_id"], "raw": q["raw"], "normalized": q["engine_projection"],
                     "view_id": view_ids[q["source_span_id"]]} for q in amounts_of(packet)],
        "persons": [{"person_id": p["person_id"], "surface": p["surface"],
                     "proposal_kind": "target_mention" if p["kind"] == "target" else p["kind"],
                     "mention_count": len(p["mentions"])} for p in persons]}, ensure_ascii=False)


def validate(payload: dict, packet: dict, persons: list[dict]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload_not_object")
    pids = {p["person_id"] for p in persons}
    qids = {q["candidate_id"] for q in amounts_of(packet)}
    ps = payload.get("persons")
    if not isinstance(ps, list) or {p.get("person_id") for p in ps if isinstance(p, dict)} != pids or len(ps) != len(pids):
        raise ValueError("persons_not_complete")
    if any(p.get("is_target") not in TRI for p in ps):
        raise ValueError("invalid_is_target")
    am = payload.get("amounts")
    if not isinstance(am, list) or {a.get("candidate_id") for a in am if isinstance(a, dict)} != qids or len(am) != len(qids):
        raise ValueError("amounts_not_complete")
    for a in am:
        if a.get("scene_total") not in TRI:
            raise ValueError("invalid_scene_total")
        links = a.get("links")
        if not isinstance(links, list) or {l.get("person_id") for l in links if isinstance(l, dict)} != pids \
                or len(links) != len(pids):
            raise ValueError("links_not_complete")
        if any(l.get("relation") not in RELATIONS for l in links):
            raise ValueError("invalid_relation")
        holders = a.get("unlisted_holders")
        if not isinstance(holders, list) or not all(isinstance(h, str) for h in holders):
            raise ValueError("invalid_unlisted_holders")


def run(batches: list[Path], out: Path, providers: dict, names: tuple[str, ...], *, workers: int,
        cap: float, max_calls: int, max_tokens: int, ids: set[str] | None, execute: bool,
        abandon_unknown: bool = False, revive: bool = False) -> dict:
    records = []
    for batch in batches:
        manifest = json.loads((batch / "MANIFEST.json").read_text("utf-8"))
        source = batch / "inputs.jsonl"
        if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["inputs_sha256"]:
            raise ValueError("batch_hash_mismatch:" + batch.name)
        records += [dict(r, batch=batch.name) for r in rows(source)]
    for name in names:
        providers[name].max_tokens, providers[name].temperature = max_tokens, 0
        if providers[name].model.startswith("qwen"):
            providers[name].extra_body = {"thinking_budget": max_tokens // 2}
    out.mkdir(parents=True, exist_ok=True)
    labels = out / "labels"
    labels.mkdir(exist_ok=True)
    calls = DurableCalls(out / "calls", providers, prices=load_prices(data_root() / "config/s1_prices.json"),
                         cap=cap, max_calls=max_calls, max_input_bytes=40000, execute=execute,
                         revive=revive)
    abandoned = calls.abandon_unknown() if abandon_unknown else 0
    lock, stop = threading.Lock(), threading.Event()
    dead: set[str] = set()
    stats = {"abandoned_attempts_closed": abandoned, "records": len(records), "with_amounts": 0, "jobs": 0, "success": 0, "failed": 0, "existing": 0}

    def label(record: dict, packet: dict, persons: list[dict], user: str, name: str) -> None:
        if stop.is_set() or name in dead:
            return
        try:
            payload = calls.call(name, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                 context={"id": record["id"], "source": record["source_sha256"],
                                          "prompt": PROMPT_VERSION, "provider_tag": name},
                                 validator=lambda x: validate(x, packet, persons), repairs=1)
            dest = labels / f"{record['id']}-{name}.json"
            tmp = dest.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump({"id": record["id"], "batch": record["batch"], "source_sha256": record["source_sha256"],
                           "provider": name, "model": providers[name].model, "prompt_version": PROMPT_VERSION,
                           "persons": persons, "label_provenance": "model_draft", "human_review": False,
                           "annotation": payload}, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(dest)
            with lock:
                stats["success"] += 1
                append(out / "diagnostics.jsonl", {"id": record["id"], "provider": name, "status": "ok"})
        except Exception as exc:
            with lock:
                stats["failed"] += 1
                append(out / "diagnostics.jsonl", {"id": record["id"], "provider": name, "status": "error",
                                                   "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            if "budget_stop" in str(exc):
                stop.set()
            elif "provider_disabled" in str(exc) or "HTTP 402" in str(exc):
                # A dead provider (e.g. out of balance) stops only its own jobs.
                with lock:
                    dead.add(name)

    jobs = []
    for record in records:
        if ids is not None and record["id"] not in ids:
            continue
        packet = build_packet(record["text_full"], record, record_id=record["id"])
        if not amounts_of(packet):
            continue
        stats["with_amounts"] += 1
        persons = persons_of(packet, record)
        for name in names:
            if (labels / f"{record['id']}-{name}.json").exists():
                stats["existing"] += 1
            else:
                jobs.append((record, packet, persons, prompt_for(record, packet, persons), name))
    stats["jobs"] = len(jobs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in [pool.submit(label, *j) for j in jobs]:
            f.result()
    stats.update(stopped=stop.is_set(), submitted_calls=calls.used_calls, reserved_yuan=round(calls.reserved, 4))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--providers", default="bailian,deepseek")
    ap.add_argument("--alias", action="append", default=[], help="alias=base:model")
    ap.add_argument("--ids", type=Path)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--cap", type=float, default=20.0)
    ap.add_argument("--max-calls", type=int, default=1500)
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--revive", action="store_true", help="retry providers previously disabled for balance/auth")
    ap.add_argument("--abandon-unknown", action="store_true",
                    help="book in-flight attempts of a killed run at full reservation, then resubmit")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    providers, _, _ = load_config()
    for spec in args.alias:
        alias, rest = spec.split("=", 1)
        base, model = rest.split(":", 1)
        clone = copy.copy(providers[base])
        clone.name, clone.model = alias, model
        providers[alias] = clone
    print(json.dumps(run(args.batch, args.out, providers, tuple(args.providers.split(",")), workers=args.workers,
                         cap=args.cap, max_calls=args.max_calls, max_tokens=args.max_tokens,
                         ids=set(args.ids.read_text("utf-8").split()) if args.ids else None,
                         execute=args.execute, abandon_unknown=args.abandon_unknown,
                         revive=args.revive), ensure_ascii=False))


if __name__ == "__main__":
    main()

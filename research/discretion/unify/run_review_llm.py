"""Double-blind field review by two model families (qwen + deepseek) on review4 tasks.

Each model sees exactly what the Claude reviewers saw (review4 task: guide, target,
aliases, visible text, amount candidates) plus the round's GUIDE-ADDENDUM, and answers
in the review4 schema, so answers merge and score with review4 unchanged. It also lists
every natural person mentioned in the facts (verbatim surface), which serves as the
reference for the person-mention layer. The two models never see each other's answers.
Raw replies and paid-attempt receipts stay private; answers are model drafts, not gold.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from durable_calls import DurableCalls, append
from progress import load_prices
from review4 import GUIDE, SCHEMA, problems_of
from s1 import data_root, load_config

PROMPT_VERSION = "review4-llm-1"
TRI = {"yes", "no", "uncertain"}
PERSONS = """

五、人物 persons：列出 facts 原文中出现的每一个自然人提及（参赌人员、组织者、提供场所者、庄家、被提到的其他人），
按原文逐字照抄写法（如“钱xx”“张萍波”“王某某”），同一写法只列一次；不列执法人员、机关、单位、地名，也不列
“申请人”“违法行为人”这类称呼本身。is_target 表示该写法是否指目标人（yes/no/uncertain）。没有其他人时只列目标的写法。"""


def system_prompt(task: dict, addendum: str) -> str:
    schema = dict(SCHEMA, persons=[{"surface": "原文写法", "is_target": "yes|no|uncertain"}])
    # Always the current review4 guide: older task files (H3) carry an amounts-only guide.
    return (GUIDE + PERSONS + "\n\n" + addendum.strip() + "\n\nanswer_schema：\n"
            + json.dumps(schema, ensure_ascii=False))


def user_prompt(task: dict) -> str:
    return json.dumps({k: task[k] for k in ("target", "aliases", "visible_text", "amount_candidates")},
                      ensure_ascii=False)


def validate(ans: dict, task: dict) -> list[str]:
    """Raise on structural problems; return non-verbatim evidence as warnings (kept, not repaired)."""
    if not isinstance(ans, dict):
        raise ValueError("answer_not_object")
    problems = problems_of(ans, task)
    hard = [p for p in problems if not p.endswith("evidence_not_verbatim")]
    persons = ans.get("persons")
    if not isinstance(persons, list) or not all(
            isinstance(p, dict) and isinstance(p.get("surface"), str) and p.get("is_target") in TRI for p in persons):
        hard.append("persons:format")
    if hard:
        raise ValueError("; ".join(hard))
    return [p for p in problems if p.endswith("evidence_not_verbatim")]


def run(root: Path, out: Path, providers: dict, names: tuple[str, ...], *, workers: int, cap: float,
        max_calls: int, max_tokens: int, ids: set[str] | None, execute: bool, addendum: Path | None = None) -> dict:
    addendum = (addendum or root / "GUIDE-ADDENDUM.txt").read_text("utf-8")
    tasks = {p.stem: json.loads(p.read_text("utf-8")) for p in sorted((root / "tasks").glob("*.json"))}
    for name in names:
        providers[name].max_tokens, providers[name].temperature = max_tokens, 0
        if providers[name].model.startswith("qwen"):
            providers[name].extra_body = {"thinking_budget": max_tokens // 2}
    (out / "labels").mkdir(parents=True, exist_ok=True)
    calls = DurableCalls(out / "calls", providers, prices=load_prices(data_root() / "config/s1_prices.json"),
                         cap=cap, max_calls=max_calls, max_input_bytes=60000, execute=execute)
    lock, stop, dead = threading.Lock(), threading.Event(), set()
    stats = {"tasks": len(tasks), "jobs": 0, "success": 0, "failed": 0, "existing": 0}

    def label(rid: str, task: dict, name: str) -> None:
        if stop.is_set() or name in dead:
            return
        warnings: list[str] = []

        def check(ans):
            warnings[:] = validate(ans, task)

        try:
            ans = calls.call(name, [{"role": "system", "content": system_prompt(task, addendum)},
                                    {"role": "user", "content": user_prompt(task)}],
                             context={"id": rid, "prompt": PROMPT_VERSION, "provider_tag": name},
                             validator=check, repairs=1)
            dest = out / "labels" / f"{rid}-{name}.json"
            tmp = dest.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump({"id": rid, "provider": name, "model": providers[name].model,
                           "prompt_version": PROMPT_VERSION, "warnings": warnings,
                           "label_provenance": "model_draft", "answer": ans}, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(dest)
            with lock:
                stats["success"] += 1
                append(out / "diagnostics.jsonl", {"id": rid, "provider": name, "status": "ok"})
        except Exception as exc:  # noqa: BLE001 - each failure is logged per job
            with lock:
                stats["failed"] += 1
                append(out / "diagnostics.jsonl", {"id": rid, "provider": name, "status": "error",
                                                   "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            if "budget_stop" in str(exc):
                stop.set()
            elif "provider_disabled" in str(exc) or "HTTP 402" in str(exc) or "HTTP 401" in str(exc):
                with lock:
                    dead.add(name)

    jobs = []
    for rid, task in tasks.items():
        if ids is not None and rid not in ids:
            continue
        for name in names:
            if (out / "labels" / f"{rid}-{name}.json").exists():
                stats["existing"] += 1
            else:
                jobs.append((rid, task, name))
    stats["jobs"] = len(jobs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in [pool.submit(label, *j) for j in jobs]:
            f.result()
    stats.update(stopped=stop.is_set(), dead=sorted(dead), submitted_calls=calls.used_calls,
                 reserved_yuan=round(calls.reserved, 4))
    return stats


def export_passes(root: Path, out: Path, names: tuple[str, str]) -> dict:
    """Write each model's answers as a review4 pass (pass1 = first provider, pass2 = second),
    so `review4.py merge` and the adjudication flow run unchanged on model drafts."""
    counts = {}
    for pass_name, name in zip(("pass1", "pass2"), names):
        (root / pass_name).mkdir(exist_ok=False)
        n = 0
        for label in sorted((out / "labels").glob(f"*-{name}.json")):
            row = json.loads(label.read_text("utf-8"))
            (root / pass_name / f"{row['id']}.json").write_text(
                json.dumps(row["answer"], ensure_ascii=False, indent=1), "utf-8")
            n += 1
        counts[pass_name] = {"provider": name, "answers": n}
    (root / "PASSES.json").write_text(json.dumps({"source": str(out), "prompt_version": PROMPT_VERSION,
                                                  "nature": "model_draft_double_blind", **counts},
                                                 ensure_ascii=False, indent=1) + "\n", "utf-8")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="review4 directory with tasks/ and GUIDE-ADDENDUM.txt")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--providers", default="bailian,deepseek")
    ap.add_argument("--alias", action="append", default=[], help="alias=base:model")
    ap.add_argument("--ids", type=Path)
    ap.add_argument("--addendum", type=Path, help="GUIDE-ADDENDUM to use (default: ROOT/GUIDE-ADDENDUM.txt)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--cap", type=float, default=25.0, help="budget cap in yuan for this output directory")
    ap.add_argument("--max-calls", type=int, default=800)
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--export-passes", action="store_true",
                    help="after the run, write answers into ROOT/pass1 and ROOT/pass2 for review4 merge")
    args = ap.parse_args()
    providers, _, _ = load_config()
    for spec in args.alias:
        alias, rest = spec.split("=", 1)
        base, model = rest.split(":", 1)
        clone = copy.copy(providers[base])
        clone.name, clone.model = alias, model
        providers[alias] = clone
    print(json.dumps(run(args.root, args.out, providers, tuple(args.providers.split(",")), workers=args.workers,
                         cap=args.cap, max_calls=args.max_calls, max_tokens=args.max_tokens,
                         ids=set(args.ids.read_text("utf-8").split()) if args.ids else None,
                         execute=args.execute, addendum=args.addendum), ensure_ascii=False))
    if args.export_passes:
        print(json.dumps(export_passes(args.root, args.out, tuple(args.providers.split(",")[:2])), ensure_ascii=False))


if __name__ == "__main__":
    main()

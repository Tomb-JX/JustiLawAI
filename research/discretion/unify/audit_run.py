"""Read-only crash-recovery and cost audit; settlement is an explicit, evidence-backed step."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from durable_calls import append, read_rows


def audit(run: Path):
    paths = [run / name for name in ("attempts.jsonl", "raws.jsonl", "manifest.json", "execution-manifest.json")]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}
    events, raws = read_rows(paths[0]), read_rows(paths[1])
    submitted, completed = {}, {}
    issues = []
    for e in events:
        if e["event"] == "submitted":
            if e["attempt_id"] in submitted:
                issues.append("duplicate_attempt_id")
            submitted[e["attempt_id"]] = e
        elif e["event"] == "finished":
            if e["attempt_id"] in completed:
                issues.append("duplicate_completion_id")
            completed[e["attempt_id"]] = e
    raw_ids = {r["attempt_id"] for r in raws}
    unknown = sorted(submitted.keys() - completed.keys())
    issues += ["completion_without_raw:" + key for key in completed if key not in raw_ids]
    issues += ["completion_without_submission:" + key for key in completed if key not in submitted]
    costs = sum(completed[key]["charged"] if key in completed else row["reservation"] for key, row in submitted.items())
    return {"version": "run-audit-1", "attempts": len(submitted), "raw_responses": len(raws),
            "estimated_charged_or_reserved": costs, "unknown_attempts": unknown,
            "raw_recoverable_without_new_call": sorted(raw_ids & set(unknown)),
            "by_provider": dict(Counter(e["provider"] for e in submitted.values())),
            "issues": issues, "source_hashes": hashes, "automatic_resubmission": False,
            "remote_billing_confirmed": False}


def settle(run: Path, attempt_id: str, charged: float, *, evidence: str, scope_dir=None):
    """人工核账出口：对某未知提交按远端账单实证写 finished（绝不重发 HTTP）。
    evidence 必填——没有账单依据就不许清 unknown（审计 P0-5："先人工核账"落成命令）。"""
    events = read_rows(run / "attempts.jsonl")
    submitted = {e["attempt_id"]: e for e in events if e["event"] == "submitted"}
    completed = {e["attempt_id"] for e in events if e["event"] == "finished"}
    if attempt_id not in submitted:
        raise ValueError("unknown_attempt_id:账本里查无此提交")
    if attempt_id in completed:
        raise ValueError("already_finished:不得对已结算提交二次核账")
    if not (evidence or "").strip():
        raise ValueError("settlement_requires_evidence:须附远端账单/控制台依据")
    ev = submitted[attempt_id]
    if charged > ev["reservation"] * 4 + 0.01:
        raise ValueError("implausible_charged:实收超预留 4 倍，先排查 token 口径再核账")
    row = {"event": "finished", "key": ev["key"], "attempt_id": attempt_id,
           "charged": charged, "usage": {}, "manual_reconcile": True, "evidence": evidence}
    append(run / "attempts.jsonl", row)
    if scope_dir is not None:
        from budget_scope import BudgetScope
        policy = json.loads((scope_dir / "policy.json").read_text("utf-8"))
        BudgetScope(Path(scope_dir), cap=policy["cap"], max_calls=policy["max_calls"]).settle(ev["key"], charged)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--settle", metavar="ATTEMPT_ID", help="对指定未知提交做人工核账（配 --charged/--evidence）")
    p.add_argument("--charged", type=float, help="核账实收金额（元）；0=确认远端未计费")
    p.add_argument("--evidence", default="", help="远端控制台/账单依据（URL 或截图路径+日期）")
    p.add_argument("--scope-dir", type=Path, help="同步结算共享预算账本（budget_scope 目录）")
    a = p.parse_args()
    if a.settle:
        if a.charged is None:
            p.error("--settle 必须给出 --charged（确认未计费请显式传 0）")
        print(json.dumps(settle(a.run, a.settle, a.charged,
                                evidence=a.evidence, scope_dir=a.scope_dir), ensure_ascii=False, indent=2))
    print(json.dumps(audit(a.run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

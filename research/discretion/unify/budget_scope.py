"""Cross-process, cross-stage budget reservations with append-only recovery audit."""
from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

VERSION = "budget-scope-1"


def _amount(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid_budget_amount")
    return Decimal(str(value))


class BudgetScope:
    def __init__(self, root: Path, *, cap: float, max_calls: int):
        _amount(cap)
        if cap <= 0 or type(max_calls) is not int or max_calls <= 0:
            raise ValueError("invalid_budget_scope_limits")
        self.root, self.cap, self.max_calls = Path(root), cap, max_calls
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock():
            policy = {"version": VERSION, "cap": cap, "max_calls": max_calls}
            path = self.root / "policy.json"
            if path.exists() and json.loads(path.read_text("utf-8")) != policy:
                raise ValueError("budget_scope_policy_changed")
            if not path.exists():
                self._append(path, policy, overwrite=True)

    @contextmanager
    def _lock(self):
        path = self.root / "WRITER.lock"
        deadline = time.monotonic() + 5
        while True:
            try:
                f = path.open("x", encoding="ascii")
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("budget_scope_locked:确认进程后恢复，不自动抢锁")
                time.sleep(.025)
        try:
            with f:
                f.write(str(os.getpid()))
            yield
        finally:
            path.unlink()

    @staticmethod
    def _append(path, row, overwrite=False):
        with path.open("x" if overwrite else "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _events(self):
        path = self.root / "ledger.jsonl"
        return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()] if path.exists() else []

    def snapshot(self):
        events = self._events()
        reserved = {e["key"]: e for e in events if e["event"] == "reserved"}
        settled = {e["key"]: e for e in events if e["event"] == "settled"}
        used = sum((_amount(settled[k]["charged"] if k in settled else e["amount"]) for k, e in reserved.items()), Decimal(0))
        return {"calls": len(reserved), "used_or_reserved": float(used),
                "unknown_keys": sorted(reserved.keys() - settled.keys()), "cap": self.cap,
                "max_calls": self.max_calls, "_reserved": reserved, "_settled": settled}

    def reserve(self, key, amount, *, owner):
        _amount(amount)
        with self._lock():
            state = self.snapshot()
            if key in state["_reserved"]:
                raise RuntimeError("shared_attempt_exists:不能跨批重复购买请求")
            if (state["calls"] >= self.max_calls
                    or _amount(state["used_or_reserved"]) + _amount(amount) > _amount(self.cap)):
                raise RuntimeError("shared_budget_stop")
            self._append(self.root / "ledger.jsonl", {"event": "reserved", "key": key, "amount": amount, "owner": owner})

    def settle(self, key, charged):
        _amount(charged)
        with self._lock():
            state = self.snapshot()
            if key not in state["_reserved"]:
                raise ValueError("settle_without_reservation")
            if key in state["_settled"]:
                if state["_settled"][key]["charged"] != charged:
                    raise ValueError("settlement_mismatch")
                return
            self._append(self.root / "ledger.jsonl", {"event": "settled", "key": key, "charged": charged})


def from_order(order, data_root):
    spec = order.get("budget_scope")
    if not spec:
        raise ValueError("跨阶段执行须登记共享 budget_scope；不能各入口重获总预算")
    root = Path(spec["path"]).resolve()
    if not root.is_relative_to((data_root / "s1_runs").resolve()):
        raise ValueError("budget_scope 只写 $DATA/s1_runs")
    return BudgetScope(root, cap=spec["cap"], max_calls=spec["max_calls"])

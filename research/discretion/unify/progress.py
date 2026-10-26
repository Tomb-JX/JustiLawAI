"""模型调用的进度心跳 / 错误分类 / 费用计量 / 熔断器（监控基建，2026-10-17）。

- ProgressTracker：原子写 progress.json（每件完成即写，tmp+rename 防半写）；
  字段：进度/ETA/速率/分提供商 token 与估算费用/重试分布/失败分类/最近失败样本。
- classify_error：失败签名分类（balance/auth/rate_limit/timeout/server/json/empty/other）。
- CostMeter：价格表 $DATA/config/s1_prices.json（元/百万 token，按模型键）；无价格只计数。
- 熔断：balance/auth 类失败一次即判死该提供商（确定性故障，重试无意义）；
  其他类连续 3 次判死；全部提供商判死 → phase=aborted 整 run 快速中止。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

_FATAL_CATEGORIES = {"balance", "auth"}
_CONSEC_FATAL = 3


def classify_error(err: str) -> str:
    e = err or ""
    if "HTTP 402" in e or "Insufficient Balance" in e:
        return "balance"
    if "HTTP 401" in e:
        return "auth"
    if "HTTP 429" in e or "rate limit" in e.lower():
        return "rate_limit"
    if "TimeoutError" in e or "timed out" in e:
        return "timeout"
    if e.startswith("HTTP 5"):
        return "server"
    if "JSON" in e:
        return "json"
    if "空返回" in e:
        return "empty"
    return "other"


class CostMeter:
    """按模型键计 token 与估算费用（价格表 元/百万 token；缺价格只计数）。"""

    def __init__(self, prices: dict | None = None):
        self.prices = prices or {}
        self.usage: dict[str, dict] = {}   # model -> {calls, prompt, completion, cost}
        self._lock = threading.Lock()

    def add(self, model: str, usage: dict) -> None:
        pt = (usage or {}).get("prompt_tokens") or 0
        ct = (usage or {}).get("completion_tokens") or 0
        price = self.prices.get(model) or {}
        cost = pt / 1e6 * price.get("input", 0) + ct / 1e6 * price.get("output", 0) \
            if price else None
        with self._lock:
            m = self.usage.setdefault(model, {"calls": 0, "prompt": 0, "completion": 0, "cost": 0.0})
            m["calls"] += 1
            m["prompt"] += pt
            m["completion"] += ct
            if cost is not None:
                m["cost"] = round(m["cost"] + cost, 4)

    def total(self) -> dict:
        with self._lock:
            tot = {"calls": sum(m["calls"] for m in self.usage.values()),
                   "tokens": sum(m["prompt"] + m["completion"] for m in self.usage.values()),
                   "cost": round(sum(m["cost"] for m in self.usage.values()), 4),
                   "priced": bool(self.prices)}
            return tot

    def snapshot(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self.usage.items()}


class ProgressTracker:
    """进度心跳：原子写 progress.json；线程安全（多工位并发回填）。"""

    def __init__(self, run_dir: Path, total: int, meta: dict, prices: dict | None = None):
        self.path = run_dir / "progress.json"
        self.run_dir = run_dir
        self.meta = meta
        self.total = total
        self.started = datetime.now()
        self._lock = threading.Lock()
        self.done = 0
        self.ok = 0
        self.fail = 0
        self.in_flight = 0
        self.phase = "running"
        self.errors_recent: list[dict] = []
        self.attempts: Counter = Counter()
        self.err_cats: Counter = Counter()
        self.latencies: list[int] = []
        self.cost = CostMeter(prices)
        self._write()

    def begin_record(self) -> None:
        with self._lock:
            self.in_flight += 1
        self._write()

    def finish_record(self, ok: bool, attempts: int, provider: str, error: str = "",
                      latency_ms: int = 0) -> None:
        with self._lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.done += 1
            if ok:
                self.ok += 1
            else:
                self.fail += 1
            self.attempts[attempts] += 1
            if latency_ms:
                self.latencies.append(latency_ms)
            if error:
                cat = classify_error(error)
                self.err_cats[cat] += 1
                self.errors_recent.append({"ts": datetime.now().isoformat(timespec="seconds"),
                                           "provider": provider, "cat": cat, "error": error[:120]})
                self.errors_recent = self.errors_recent[-10:]
        self._write()

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = phase
        self._write()

    def note_cost(self, cost: CostMeter) -> None:
        self.cost = cost
        self._write()

    def _snapshot(self) -> dict:
        lat = sorted(self.latencies)
        elapsed = (datetime.now() - self.started).total_seconds()
        remain = max(0, self.total - self.done)
        rate = self.done / elapsed * 60 if elapsed > 0 else 0
        return {
            **self.meta,
            "phase": self.phase, "total": self.total,
            "done": self.done, "ok": self.ok, "fail": self.fail,
            "in_flight": self.in_flight,
            "started": self.started.isoformat(timespec="seconds"),
            "elapsed_min": round(elapsed / 60, 1),
            "rate_rpm": round(rate, 2),
            "eta_min": round(remain / rate, 1) if rate > 0 else None,
            "latency_ms_p50": lat[len(lat) // 2] if lat else None,
            "latency_ms_p90": lat[int(len(lat) * 0.9)] if lat else None,
            "attempts_dist": dict(self.attempts),
            "error_categories": dict(self.err_cats),
            "errors_recent": self.errors_recent,
            "tokens_by_model": self.cost.snapshot(),
            "cost_total": self.cost.total(),
            "updated": datetime.now().isoformat(timespec="seconds"),
        }

    def _write(self) -> None:
        """原子写；Windows 上目标被瞬时占用（读者/杀毒/索引器）时重试，仍失败降级为
        直接覆盖——心跳是次要组件，任何写失败都不得传播到主管线。"""
        payload = json.dumps(self._snapshot(), ensure_ascii=False, indent=1)
        tmp = self.path.with_suffix(".tmp")
        for _ in range(5):
            try:
                tmp.write_text(payload, encoding="utf-8", newline="\n")
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.2)
            except OSError:
                break
        try:   # 降级：直接覆盖（放弃原子性，保住"不崩溃"）
            self.path.write_text(payload, encoding="utf-8", newline="\n")
            if tmp.exists():
                os.remove(tmp)
        except OSError:
            pass   # 心跳丢失可容忍（下一条完成时重写）


def load_prices(path: Path) -> dict:
    """价格表：{模型键: {"input": 元/百万, "output": 元/百万}}；缺文件=只计数不折价。"""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

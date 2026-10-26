"""Bounded HTTP attempts with recoverable raw responses and budget reservations.

JSONL is an append-only attempt ledger, not a promise of exactly-once remote billing.
Unknown submitted attempts remain reserved and are not automatically resubmitted.
"""
from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

from element_contract import digest
from progress import classify_error
from s1 import extract_json, ProviderResponseError


def append(path: Path, row: dict):
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_rows(path):
    if not path.exists():
        return []
    # A torn tail is an explicit recovery error, not silently discarded work.
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def provider_identity(provider):
    host = (urlparse(provider.base_url).hostname or "").lower()
    if host.endswith("deepseek.com"):
        return "deepseek"
    if host.endswith("xiaomimimo.com"):
        return "xiaomi"
    return host


def check_models(a, b, c):
    from arbitrate import ARBITER_MODEL_WHITELIST
    if provider_identity(a) == provider_identity(b):
        raise ValueError("A/B 必须不同提供方，不能以配置键伪装隔离")
    if provider_identity(c) == "deepseek" or c.model not in ARBITER_MODEL_WHITELIST:
        raise ValueError("C 必须是已登记的非 DeepSeek 裁判")


class DurableCalls:
    def __init__(self, out: Path, providers: dict, *, prices: dict, cap: float,
                 max_calls: int, max_input_bytes: int, execute=False, budget_scope=None, revive=False):
        if (type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0
                or type(max_calls) is not int or max_calls <= 0
                or type(max_input_bytes) is not int or max_input_bytes <= 0):
            raise ValueError("invalid_call_limits")
        self.out, self.providers, self.prices = Path(out), providers, prices
        self.out.mkdir(parents=True, exist_ok=True)
        self.cap, self.max_calls = cap, max_calls
        self.max_input_bytes, self.execute = max_input_bytes, execute
        self.budget_scope = budget_scope
        self.lock = threading.Lock()
        self.events = read_rows(self.out / "attempts.jsonl")
        self.raws = {r["key"]: r for r in read_rows(self.out / "raws.jsonl")}
        self.used_calls = sum(r["event"] == "submitted" for r in self.events)
        submitted = {r["attempt_id"]: r for r in self.events if r["event"] == "submitted"}
        self.dead = {submitted[r["attempt_id"]]["provider"] for r in self.events
                     if r["event"] == "failed" and r.get("category") in ("balance", "auth")
                     and r["attempt_id"] in submitted}
        if revive:
            # Explicit operator decision after a top-up: forget past balance/auth failures.
            self.dead = set()
        completed = {r["attempt_id"]: r for r in self.events if r["event"] == "finished"}
        # Raw without the finished marker is recoverable without another HTTP request,
        # but its reservation remains held until the ledger is explicitly reconciled.
        self.reserved = sum(completed[k]["charged"] if k in completed else r["reservation"]
                            for k, r in submitted.items())
        self.unknown = {r["key"] for k, r in submitted.items() if k not in completed}

    def abandon_unknown(self) -> int:
        """Close attempts whose process died in flight, charging the full reservation.

        The remote outcome stays unknown, so cost is booked at the conservative
        maximum; the key may then be resubmitted as a new attempt.
        """
        submitted = {r["attempt_id"]: r for r in self.events if r["event"] == "submitted"}
        finished = {r["attempt_id"] for r in self.events if r["event"] == "finished"}
        closed = 0
        with self.lock:
            for attempt, row in submitted.items():
                if attempt in finished or row["key"] in self.raws:
                    continue
                append(self.out / "attempts.jsonl", {"event": "finished", "key": row["key"],
                       "attempt_id": attempt, "charged": row["reservation"], "abandoned": True})
                self.unknown.discard(row["key"])
                closed += 1
        return closed

    def call(self, provider_name, msgs, *, context, validator, repairs=1):
        provider = self.providers[provider_name]
        if type(provider.max_tokens) is not int or provider.max_tokens <= 0:
            raise ValueError("invalid_provider_max_tokens")
        request = {"context": context, "messages": msgs, "provider": provider_identity(provider),
                   "endpoint": provider.base_url, "model": provider.model,
                   "max_tokens": provider.max_tokens, "temperature": provider.temperature}
        if getattr(provider, "extra_body", None):
            # Only non-empty extras enter the key, so existing replay caches keep their keys.
            request["extra_body"] = provider.extra_body
        key = digest(request)
        if key in self.raws:
            # Validation failures stay visible; a cached invalid response is not a success.
            cached = self.raws[key]
            try:
                result = extract_json(cached["content"])
                validator(result)
                return result
            except (ValueError, TypeError) as exc:
                if not self.execute:
                    raise ValueError(f"cached_invalid:{exc}") from exc
                msgs = [dict(m) for m in msgs]
                msgs[-1]["content"] += "\n纠正上次无效输出：" + str(exc)[:800]
                context = {**context, "repair_of": key}
                if repairs < 1:
                    raise
                return self.call(provider_name, msgs, context=context,
                                 validator=validator, repairs=repairs - 1)
        if key in self.unknown:
            raise RuntimeError("unknown_remote_outcome:先人工核账，不自动重复付费请求")
        if not self.execute:
            raise RuntimeError("replay_cache_miss:未授权实际调用")
        size = sum(len(m["content"].encode("utf-8")) for m in msgs) + 1024
        if size > self.max_input_bytes:
            raise ValueError("request_too_large:完整请求超预算，不截断原文或 JSON")
        price = self.prices.get(provider.model)
        if not price or not all(k in price for k in ("input", "output")):
            raise ValueError("missing_price:无法预留费用")
        if any(type(price[k]) not in (int, float) or not math.isfinite(price[k]) or price[k] < 0 for k in ("input", "output")):
            raise ValueError("invalid_registered_price")
        # UTF-8 bytes + explicit framing allowance is a conservative token estimate;
        # reasoning tokens are bounded by provider max_tokens and charged as output.
        reservation = (size * price["input"] + provider.max_tokens * price["output"]) / 1e6
        with self.lock:
            if key in self.unknown or key in self.raws:
                raise RuntimeError("concurrent_task_exists:只可本地重读，不重复发请求")
            identity = provider_identity(provider)
            if identity in self.dead:
                raise RuntimeError("provider_disabled")
            if self.used_calls >= self.max_calls or self.reserved + reservation > self.cap:
                raise RuntimeError("budget_stop:包含在飞和未知请求的预留")
            attempt = f"{key}:{self.used_calls + 1}"
            if self.budget_scope:
                self.budget_scope.reserve(key, reservation, owner=str(self.out.resolve()))
            append(self.out / "attempts.jsonl", {"event": "submitted", "key": key,
                   "attempt_id": attempt, "reservation": reservation, "provider": identity,
                   "model": provider.model, "context": context, "request_hash": digest(msgs), "price": price})
            self.used_calls += 1
            self.reserved += reservation
            self.unknown.add(key)
        try:
            content, meta = provider.chat(msgs[0]["content"], msgs[1]["content"])
        except ProviderResponseError as exc:
            content, meta = exc.content, exc.meta  # known HTTP response: persist and charge normally
        except Exception as exc:
            category = classify_error(str(exc))
            with self.lock:
                # A failed HTTP request can still have unknown remote cost. Keep full reserve.
                append(self.out / "attempts.jsonl", {"event": "failed", "key": key,
                       "attempt_id": attempt, "category": category,
                       "error_type": type(exc).__name__})
                if category in ("balance", "auth"):
                    self.dead.add(provider_identity(provider))
            raise
        with self.lock:
            raw = {"key": key, "attempt_id": attempt, "content": content,
                   "meta": meta, "context": context, "provider": identity, "model": provider.model}
            append(self.out / "raws.jsonl", raw)  # durable BEFORE parsing/validation
            self.raws[key] = raw
            usage = meta.get("usage") or {}
            if any(type(usage[k]) is not int or usage[k] < 0 for k in ("prompt_tokens", "completion_tokens") if k in usage):
                raise ValueError("invalid_provider_usage:保留预留并人工核账")
            charged = ((usage["prompt_tokens"] * price["input"]
                        + usage["completion_tokens"] * price["output"]) / 1e6
                       if all(k in usage for k in ("prompt_tokens", "completion_tokens")) else reservation)
            append(self.out / "attempts.jsonl", {"event": "finished", "key": key,
                   "attempt_id": attempt, "charged": charged, "usage": usage})
            if self.budget_scope:
                self.budget_scope.settle(key, charged)
            self.reserved += charged - reservation
            self.unknown.discard(key)
            overrun = charged > reservation
        if overrun:
            self.dead.add(identity)
            raise RuntimeError("reservation_exceeded:检查服务端 token 口径后再继续")
        try:
            payload = extract_json(content)
            validator(payload)
            return payload
        except (ValueError, TypeError) as exc:
            if repairs < 1:
                raise
            repaired = [dict(m) for m in msgs]
            repaired[-1]["content"] += "\n纠正上次无效输出：" + str(exc)[:800]
            return self.call(provider_name, repaired, context={**context, "repair_of": key},
                             validator=validator, repairs=repairs - 1)

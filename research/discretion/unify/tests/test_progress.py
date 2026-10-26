"""监控基建单测：错误分类 / 进度心跳原子写 / 费用计量 / 熔断跳过（合成 Provider，无 API）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from progress import ProgressTracker, classify_error, load_prices  # noqa: E402
from s1 import Runner, validate  # noqa: E402


def test_classify_error():
    assert classify_error('HTTP 402: Insufficient Balance') == "balance"
    assert classify_error("HTTP 401 unauthorized") == "auth"
    assert classify_error("HTTP 429 rate capped") == "rate_limit"
    assert classify_error("TimeoutError: The read operation timed out") == "timeout"
    assert classify_error("HTTP 500 oops") == "server"
    assert classify_error("无法提取 JSON") == "json"
    assert classify_error("空返回（finish=length）") == "empty"
    assert classify_error("其他") == "other"


def test_tracker_atomic_and_counters():
    with tempfile.TemporaryDirectory() as td:
        tr = ProgressTracker(Path(td), total=10, meta={"run_id": "t"})
        for i in range(10):
            tr.begin_record()
            tr.finish_record(ok=(i % 3 != 0), attempts=1 + i % 2,
                             provider="p", latency_ms=100 + i,
                             error="" if i % 3 != 0 else "HTTP 429 rate capped")
        p = json.loads((Path(td) / "progress.json").read_text(encoding="utf-8"))
        assert p["done"] == 10 and p["ok"] == 6 and p["fail"] == 4
        assert p["phase"] == "running" and p["in_flight"] == 0
        assert p["error_categories"] and p["attempts_dist"]
        tr.set_phase("done")
        p2 = json.loads((Path(td) / "progress.json").read_text(encoding="utf-8"))
        assert p2["phase"] == "done"


def test_cost_meter():
    from progress import CostMeter
    m = CostMeter({"m1": {"input": 2.0, "output": 8.0}})   # 元/百万
    m.add("m1", {"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
    m.add("m2", {"prompt_tokens": 1000, "completion_tokens": 1000})   # 无价格只计数
    t = m.total()
    assert t["tokens"] == 1_502_000 and abs(t["cost"] - 6.0) < 1e-6 and t["priced"]


class _FakeProv:
    def __init__(self, name, model, fail_with):
        self.name, self.model, self.fail_with = name, model, fail_with

    def chat(self, system, user):
        raise RuntimeError(self.fail_with)


def test_runner_circuit_breaker_skips_dead_provider():
    with tempfile.TemporaryDirectory() as td:
        rec = {"id": "T-1", "form": "叙述式-独立成篇", "source_type": "处罚决定书",
               "cleaned_text": "经查，张某某赌博。"}
        prov_dead = _FakeProv("dead", "dead-model", "HTTP 402: Insufficient Balance")
        prov_alive = _FakeProv("alive", "alive-model", "HTTP 429 rate")   # 也失败，但类非致命
        runner = Runner({"dead": prov_dead, "alive": prov_alive}, Path(td),
                        ["dead", "alive"], total=1)
        res = runner.extract_one(rec, primary="dead")
        # 402 一次即熔断：chain 只应有 alive 的一次尝试（dead 被跳过第二次）
        providers_tried = [c["provider"] for c in res["chain"]]
        assert providers_tried.count("dead") == 1
        assert "alive" in providers_tried
        assert "dead" in runner.dead
        prog = json.loads((Path(td) / "progress.json").read_text(encoding="utf-8"))
        assert prog["done"] >= 1 and prog["phase"] == "running"
        runner.close()   # 关闭回执句柄，Windows 才能清理临时目录


def test_validate_v2_tiling():
    out = {"zones": [{"type": "facts", "from": 1, "to": 2},
                     {"type": "decision", "from": 4, "to": 5}],   # 缺 3
           "outcome": {"type": "拘留"}, "gambling": {"verdict": "是"},
           "review": {"result": "无"}, "confidence": "high"}
    errs = validate(out, n_sentences=5)
    assert any("连续" in e or "铺满" in e for e in errs)


def test_runner_priced_meter():
    with tempfile.TemporaryDirectory() as td:
        prices = {"t-model": {"input": 2.0, "output": 8.0}}
        runner = Runner({"t": _FakeProv("t", "t-model", "never")}, Path(td),
                        ["t"], total=1, tracker_meta={})
        runner.cost_meter = __import__("progress").CostMeter(prices)
        runner.tracker.cost = runner.cost_meter
        runner.cost_meter.add("t-model", {"prompt_tokens": 500_000, "completion_tokens": 125_000})
        assert runner.tracker.cost.total()["cost"] == 2.0   # 0.5M×2 + 0.125M×8
        runner.close()

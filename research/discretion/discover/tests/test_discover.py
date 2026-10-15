"""发现层 M1 单测：规划器、缓存、预算闸门、限速与重试、饱和拆分，以及 M0 探针缓存的离线回放。

运行（仓库根目录）：python -m pytest research/discretion/discover/tests -q
不联网：所有 API 调用都走假的 transport。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from plan import Query, body_key, load_config, seeds, split
from search import Budget, Cache, Client, Ledger, import_probe, run

CFG = load_config()
# M0 探针 T2 / T8 的原始请求体（probe_qianfan.py 发出的格式）
T2_BODY = {
    "messages": [{"role": "user", "content": "行政复议决定书 赌博 治安管理处罚法第七十条 site:gov.cn"}],
    "search_source": "baidu_search_v2",
    "resource_type_filter": [{"type": "web", "top_k": 50}],
}
T8_BODY = {
    "messages": [{"role": "user", "content": "赌博 行政处罚决定书 第八十二条 site:gov.cn"}],
    "search_source": "baidu_search_v2",
    "resource_type_filter": [{"type": "web", "top_k": 50}],
    "search_recency_filter": "year",
}


def refs(n: int, tag: str) -> list[dict]:
    return [{"url": f"https://www.x{i}.gov.cn/{tag}", "title": f"{tag}{i}", "content": "赌博 行罚决字"} for i in range(n)]


class FakeTransport:
    """按 query 文本决定返回条数；记录调用。"""

    def __init__(self, full_for: set[str] = frozenset(), statuses: list[int] | None = None):
        self.full_for, self.statuses, self.calls = set(full_for), list(statuses or []), []

    def __call__(self, body: dict, key: str) -> tuple[int, dict]:
        text = body["messages"][0]["content"]
        self.calls.append(text)
        if self.statuses:
            st = self.statuses.pop(0)
            if st != 200:
                return st, {"code": "Throttled"}
        n = 50 if text in self.full_for else 7
        return 200, {"references": refs(n, text)}


def make(tmp_path: Path, transport, *, max_calls=100, max_cost=100.0, daily_cap=1000):
    sleeps: list[float] = []
    t = [0.0]
    client = Client("k", transport=transport, min_interval=1.0, clock=lambda: t[0],
                    sleep=lambda s: (sleeps.append(s), t.__setitem__(0, t[0] + s)))
    budget = Budget(max_calls, max_cost, daily_cap, Ledger(tmp_path / "ledger.csv"))
    return Cache(tmp_path / "cache"), client, budget, sleeps


# ---------- plan ----------

def test_seed_bodies_match_m0_probe():
    fy70 = Query("fy70")
    cf82 = Query("cf82")
    assert body_key(fy70.body(CFG)) == body_key(T2_BODY)
    assert body_key(cf82.body(CFG)) == body_key(T8_BODY)


def test_body_key_ignores_dict_order():
    assert body_key({"a": 1, "b": [1, 2]}) == body_key({"b": [1, 2], "a": 1})


def test_split_follows_configured_order():
    assert CFG["split"]["order"] == ["features", "windows", "regions"]
    q = Query("fy70")
    lvl1 = split(q, CFG)
    assert {c.feature for c in lvl1} == set(CFG["split"]["features"]) and all(c.depth == 1 for c in lvl1)
    lvl2 = split(lvl1[0], CFG)
    assert {c.window for c in lvl2} == set(CFG["split"]["windows"])
    assert "page_time" in lvl2[0].body(CFG)["search_filter"]["range"]
    lvl3 = split(lvl2[0], CFG)
    assert {c.region for c in lvl3} == set(CFG["split"]["regions"])
    assert split(lvl3[0], CFG) == []


def test_recency_template_skips_time_split():
    child = split(Query("cf82", feature="麻将"), CFG)
    assert child and all(c.region and c.window is None for c in child)


def test_seeds_reject_unknown():
    with pytest.raises(ValueError):
        seeds(CFG, ["nope"])
    with pytest.raises(ValueError):
        seeds(CFG, ["fy70"], ["火星"])


def test_query_ids_unique_across_tree():
    ids = {q.qid for q in split(Query("fy70"), CFG)}
    assert len(ids) == len(CFG["split"]["features"])


# ---------- search ----------

def test_cache_hit_avoids_api(tmp_path):
    tr = FakeTransport()
    cache, client, budget, _ = make(tmp_path, tr)
    qs = [Query("bycf")]
    kw = dict(cache=cache, budget=budget, client=client, offline=False, max_depth=0, seen_path=tmp_path / "seen.txt")
    s1 = run(qs, CFG, out_dir=tmp_path / "r1", **kw)
    s2 = run(qs, CFG, out_dir=tmp_path / "r2", **kw)
    assert len(tr.calls) == 1
    assert s1["api_calls"] == 1 and s2["cache_hits"] == 1
    assert s1["new_urls"] == 7 and s2["new_urls"] == 0


def test_saturated_query_splits_until_max_depth(tmp_path):
    root_text = Query("fy70").text(CFG)
    tr = FakeTransport(full_for={root_text})
    cache, client, budget, _ = make(tmp_path, tr)
    s = run([Query("fy70")], CFG, cache=cache, budget=budget, client=client, offline=False, max_depth=1,
            out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert len(tr.calls) == 1 + len(CFG["split"]["features"])
    assert s["saturated_unsplit"] == 0


def test_saturated_at_depth_limit_is_flagged(tmp_path):
    tr = FakeTransport(full_for={Query("fy70").text(CFG)})
    cache, client, budget, _ = make(tmp_path, tr)
    s = run([Query("fy70")], CFG, cache=cache, budget=budget, client=client, offline=False, max_depth=0,
            out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert s["saturated_unsplit"] == 1 and len(tr.calls) == 1


def test_budget_stops_and_defers(tmp_path):
    tr = FakeTransport()
    cache, client, budget, _ = make(tmp_path, tr, max_calls=2)
    qs = seeds(CFG, ["fy70", "cf70", "wh70", "zfgs"])
    s = run(qs, CFG, cache=cache, budget=budget, client=client, offline=False, max_depth=0,
            out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert len(tr.calls) == 2 and s["deferred"] == 2 and "--budget" in s["stop_reason"]


def test_max_cost_gate(tmp_path):
    tr = FakeTransport()
    cache, client, budget, _ = make(tmp_path, tr, max_cost=0.08)  # 0.036 × 2 = 0.072 ≤ 0.08 < 0.108
    s = run(seeds(CFG, ["fy70", "cf70", "wh70"]), CFG, cache=cache, budget=budget, client=client, offline=False,
            max_depth=0, out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert len(tr.calls) == 2 and "--max-cost" in s["stop_reason"]


def test_daily_cap_counts_previous_runs(tmp_path):
    ledger = Ledger(tmp_path / "ledger.csv")
    ledger.add("earlier", 3)
    tr = FakeTransport()
    cache, client, _, _ = make(tmp_path, tr)
    budget = Budget(100, 100.0, 4, ledger)
    s = run(seeds(CFG, ["fy70", "cf70"]), CFG, cache=cache, budget=budget, client=client, offline=False,
            max_depth=0, out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert len(tr.calls) == 1 and "--daily-cap" in s["stop_reason"]


def test_rate_limit_spaces_requests(tmp_path):
    tr = FakeTransport()
    cache, client, budget, sleeps = make(tmp_path, tr)
    run(seeds(CFG, ["fy70", "cf70", "wh70"]), CFG, cache=cache, budget=budget, client=client, offline=False,
        max_depth=0, out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert sleeps == [1.0, 1.0]


def test_retry_on_429_then_success_counts_attempts(tmp_path):
    tr = FakeTransport(statuses=[429, 200])
    cache, client, budget, sleeps = make(tmp_path, tr)
    s = run([Query("bycf")], CFG, cache=cache, budget=budget, client=client, offline=False, max_depth=0,
            out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert len(tr.calls) == 2 and s["api_calls"] == 2 and s["errors"] == 0
    assert 2 in sleeps  # 第 1 次退避 2 秒


def test_client_error_not_cached_and_not_retried(tmp_path):
    tr = FakeTransport(statuses=[400])
    cache, client, budget, _ = make(tmp_path, tr)
    s = run([Query("bycf")], CFG, cache=cache, budget=budget, client=client, offline=False, max_depth=0,
            out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert len(tr.calls) == 1 and s["errors"] == 1
    assert cache.get(body_key(Query("bycf").body(CFG))) is None


def test_offline_miss_does_not_call_or_touch_seen(tmp_path):
    cache = Cache(tmp_path / "cache")
    s = run([Query("bycf")], CFG, cache=cache, budget=None, client=None, offline=True, max_depth=1,
            out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert s["cache_misses"] == 1 and s["queries_done"] == 0
    assert not (tmp_path / "seen.txt").exists()


# ---------- M0 探针缓存回放（有真实探针输出时才跑） ----------

PROBE_DIRS = sorted((Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research")) / "discover" / "probe").glob("*"))


@pytest.mark.skipif(not PROBE_DIRS, reason="本机没有 M0 探针输出")
def test_offline_replay_of_m0_probe(tmp_path):
    cache = Cache(tmp_path / "cache")
    n = sum(import_probe(d, cache) for d in PROBE_DIRS)
    assert n >= 8  # 10 项测试里 T3（0 条，但成功）也会入缓存；T5 报错不入
    s = run(seeds(CFG, ["fy70", "cf82"]), CFG, cache=cache, budget=None, client=None, offline=True, max_depth=1,
            out_dir=tmp_path / "r", seen_path=tmp_path / "seen.txt")
    assert s["cache_hits"] == 2 and s["api_calls"] == 0
    hits = [json.loads(x) for x in (tmp_path / "r" / "hits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(hits) == s["unique_urls"] >= 60  # T2 50 条 + T8 23 条，去重后
    assert all(h["url"].split("/")[2].endswith("gov.cn") for h in hits)
    # fy70 顶到 50 条 → 按特征词拆出子查询，离线缓存里没有，记为 miss
    assert s["cache_misses"] == len(CFG["split"]["features"])

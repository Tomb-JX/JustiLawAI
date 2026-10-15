"""发现层例行化单测：选站、精扫结果解析、增量交付、栏目合并，以及用假 API 端到端跑两周。不联网。

运行（仓库根目录）：python -m pytest research/discretion/discover/tests -q
"""

from __future__ import annotations

import csv
from datetime import date

from plan import Query, load_config, seeds, seeds_incremental, seeds_sweep, split
from search import Client
from weekly import merge_columns, new_items, pick_sweep_sites, registrable_site, sweep_results, weekly

CFG = load_config()


def test_registrable_site():
    assert registrable_site("info.qinghexian.gov.cn") == "qinghexian.gov.cn"
    assert registrable_site("www.dingxing.gov.cn") == "dingxing.gov.cn"
    assert registrable_site("zwfw.dingxing.gov.cn") == "dingxing.gov.cn"
    assert registrable_site("hayexian.jcy.gov.cn") is None  # 检察系统公共域名
    assert registrable_site("www.gov.cn") is None
    assert registrable_site("news.sohu.com") is None


def test_sweep_and_incremental_seeds():
    assert all(q.template != "sw" for q in seeds(CFG))  # 精扫模板不进常规种子
    inc = seeds_incremental(CFG, "week")
    assert inc and all(q.body(CFG)["search_recency_filter"] == "week" for q in inc)
    sw = seeds_sweep(CFG, ["dingxing.gov.cn"])
    assert sw[0].text(CFG) == "赌博 site:dingxing.gov.cn" and "|s=dingxing.gov.cn" in sw[0].qid
    assert split(sw[0], CFG) == []  # 精扫顶格不拆分，交给整栏收割


def test_incremental_query_skips_time_windows():
    q = Query("fy70", recency="week")
    assert all(c.window is None for c in split(q, CFG))


def test_pick_sweep_sites_groups_hosts_and_respects_resweep():
    domains = {
        "www.dingxing.gov.cn": {"n_target": "40"}, "zwfw.dingxing.gov.cn": {"n_target": "2"},
        "info.qinghexian.gov.cn": {"n_target": "21"}, "www.npc.gov.cn": {"n_target": "0"},
        "hayexian.jcy.gov.cn": {"n_target": "5"}, "www.x.gov.cn": {"n_target": "0"},
    }
    state = {"qinghexian.gov.cn": {"date": "2026-10-10"}}
    today = date(2026, 10, 15)
    assert pick_sweep_sites(domains, state, today, max_sites=10) == ["dingxing.gov.cn"]
    assert pick_sweep_sites(domains, state, date(2026, 11, 20), max_sites=10) == ["dingxing.gov.cn", "qinghexian.gov.cn"]
    assert pick_sweep_sites(domains, {}, today, max_sites=1) == ["dingxing.gov.cn"]


def test_sweep_results_parse():
    rows = [
        {"qid": "sw|r=*|t=*|f=*|s=dingxing.gov.cn", "source": "api", "n": "50", "saturated": "unsplit"},
        {"qid": "sw|r=*|t=*|f=*|s=wei.gov.cn", "source": "cache", "n": "12", "saturated": ""},
        {"qid": "sw|r=*|t=*|f=*|s=x.gov.cn", "source": "deferred"},
        {"qid": "fy70|r=*|t=*|f=*", "source": "api", "n": "50", "saturated": "split"},
    ]
    assert sweep_results(rows) == {"dingxing.gov.cn": {"n": 50, "saturated": True},
                                   "wei.gov.cn": {"n": 12, "saturated": False}}


def test_new_items_and_merge_columns():
    assert new_items([{"url": "a"}, {"url": "b"}, {"url": ""}], {"a"}, "url") == [{"url": "b"}]
    master = [{"domain": "www.dingxing.gov.cn", "status": "ok", "entry_url": "u1"},
              {"domain": "wei.gov.cn", "status": "mixed", "entry_url": "u2"}]
    fresh = [{"domain": "www.wei.gov.cn", "status": "ok", "entry_url": "u3"},
             {"domain": "www.dingxing.gov.cn", "status": "ok", "entry_url": "u1"},
             {"domain": "www.new.gov.cn", "status": "ok", "entry_url": "u4"}]
    merged, changed = merge_columns(master, fresh)
    assert len(merged) == 3
    assert [r["entry_url"] for r in changed] == ["u3", "u4"]  # 魏县状态变了、新县；定兴没变


class FakeAPI:
    """精扫 dingxing 顶格；其余查询各回 3 条赌博处罚决定（URL 按查询区分）。"""

    def __init__(self):
        self.calls = []

    def __call__(self, body: dict, key: str):
        text = body["messages"][0]["content"]
        self.calls.append(text)
        site = text.split("site:")[1].strip()
        n = 50 if site == "dingxing.gov.cn" else 3
        host = "www.dingxing.gov.cn" if site == "gov.cn" else f"www.{site}"  # 全国增量查询的结果也落在定兴
        tag = str(abs(hash(text)) % 10**8)
        refs = [{"url": f"https://{host}/xzzfcon-467-{tag}{i}.html", "title": f"定兴公(天)行罚决字〔2026〕{tag[:3]}{i}号",
                 "content": "违法行为人张xx。现查明：张xx参与赌博，赌资300元。根据第八十二条之规定，现决定行政拘留五日。",
                 "website": "某县人民政府"} for i in range(n)]
        return 200, {"references": refs}


def test_weekly_end_to_end_twice(tmp_path):
    api = FakeAPI()
    t = [0.0]
    client = Client("k", transport=api, min_interval=0, clock=lambda: t[0], sleep=lambda s: None)
    domains_csv = tmp_path / "domains.csv"
    with open(domains_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["host", "publisher", "n_target", "n_hits", "types", "first_seen"])
        w.writerow(["www.dingxing.gov.cn", "定兴县", "40", "40", "", "2026-10-15"])
    expanded = []

    def fake_expand(hosts, cands, doms):
        expanded.extend(hosts)
        return [{"domain": h, "status": "ok", "entry_url": f"https://{h}/list", "column_id": h} for h in hosts]

    kw = dict(root=tmp_path / "discover", client=client, search_budget=30, sweep_budget=10, max_sites=5,
              daily_cap=1000, expand_min_target=3, resweep_days=28, domains_csv=domains_csv,
              weekly_log=tmp_path / "weekly-log.csv", expand_fn=fake_expand)
    r1 = weekly(today=date(2026, 10, 19), **kw)
    assert r1["sites_swept"] >= 1 and "dingxing.gov.cn" in r1["saturated"]
    assert r1["new_urls"] > 0 and r1["new_urls"] == r1["deliverable_urls"]
    assert r1["hosts_expanded"] >= 1 and r1["new_columns_ok"] >= 1
    calls_after_first = len(api.calls)

    r2 = weekly(today=date(2026, 10, 19), **kw)  # 同一天重跑：全走缓存、不重复精扫、不重复扩展、无新增交付
    assert len(api.calls) == calls_after_first
    assert r2["sites_swept"] == 0 and r2["hosts_expanded"] == 0 and r2["new_urls"] == 0
    log = list(csv.DictReader(open(tmp_path / "weekly-log.csv", encoding="utf-8")))
    assert len(log) == 2

"""档内数额：本机关 → 市 → 省 → 全国分层分布 vs 全国 × 种类，时间外推（预注册
$DATA/engine/development/agency-amounts-20261028/PREREG.md，sha256 前缀 98f52c0d32d738b1）。只运行一次：python agency_amounts.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402
from q01_band_conditioned import TASKS, legal, top2  # noqa: E402

OUT = pc.ROOT / "engine/development/agency-amounts-20261028"
K = 10
CUT, END = "2024-01-01", "2026-01-01"
SEED = 20261028


def units():
    ctx = {r["id"]: r for r in pc.jl(pc.CTX)}
    rows = pc.jl(pc.TRAIN)
    size = Counter(r["event_id"] for r in rows)
    out = []
    for r in rows:
        x = ctx.get(r["id"], {})
        d = x.get("decision_date") or ""
        if not d or d >= END:
            continue
        for task in TASKS:
            if r["target"]["type"] == task[0] and r["target"].get(task[1]) is not None:
                out.append({"id": r["id"], "event": r["event_id"], "date": d, "task": task,
                            "y": float(r["target"][task[1]]), "w": 1 / size[r["event_id"]],
                            "agency": x.get("authority_id"), "city": x.get("city_code"),
                            "prov": pc.province(x.get("province_code"), x.get("authority_id"))})
    return out


def counts(train, key):
    c = defaultdict(Counter)
    for u in train:
        k = u[key]
        if k and legal(u["task"], u["y"]):
            c[(u["task"], k)][u["y"]] += u["w"]
    return c


def shrink(cell, parent):
    tot = sum(cell.values())
    keys = set(cell) | set(parent)
    return {v: (cell.get(v, 0.0) + K * parent.get(v, 0.0)) / (tot + K) for v in keys}


def boot(a, b, events, draws=2000):
    g = defaultdict(list)
    for i, e in enumerate(events):
        g[e].append(i)
    units_ = list(g.values())
    rng = np.random.default_rng(SEED)
    d = [a[s].mean() - b[s].mean() for s in
         ([i for j in rng.integers(0, len(units_), len(units_)) for i in units_[j]] for _ in range(draws))]
    return [round(float(x), 3) for x in np.quantile(d, [0.025, 0.975])]


def main():
    us = units()
    train = [u for u in us if u["date"] < CUT]
    train_events = {u["event"] for u in train}
    test = [u for u in us if u["date"] >= CUT and u["event"] not in train_events]
    nat = {}
    for task in TASKS:
        c = Counter()
        for u in train:
            if u["task"] == task and legal(task, u["y"]):
                c[u["y"]] += u["w"]
        t = sum(c.values())
        nat[task] = {v: x / t for v, x in c.items()}
    levels = {k: counts(train, k) for k in ("prov", "city", "agency")}
    has_hist = {(u["task"], u["agency"]) for u in train if u["agency"]}
    agencies_with_hist = {u["agency"] for u in train if u["agency"]}
    rows = []
    for u in test:
        n = nat[u["task"]]
        p = n
        for k in ("prov", "city", "agency"):
            cell = levels[k].get((u["task"], u[k]))
            if cell:
                p = shrink(cell, p)
        rows.append({**u, "N": top2(n, n), "H": top2(p, n), "hist": u["agency"] in agencies_with_hist,
                     "hist_task": (u["task"], u["agency"]) in has_hist})

    def score(sel):
        if not sel:
            return {"units": 0}
        y = np.array([r["y"] for r in sel])
        res = {"units": len(sel), "events": len({r["event"] for r in sel})}
        hits = {}
        for m in ("N", "H"):
            mode = np.array([r[m][0] for r in sel])
            hits[m] = (mode == y).astype(float)
            res[m] = {"hit": round(float(hits[m].mean()), 3),
                      "top2": round(float(np.mean([r["y"] in r[m] for r in sel])), 3),
                      "mae": round(float(np.abs(mode - y).mean()), 1)}
        res["H_minus_N"] = {"diff": round(float(hits["H"].mean() - hits["N"].mean()), 3),
                            "ci95": boot(hits["H"], hits["N"], [r["event"] for r in sel])}
        return res

    main_sel = [r for r in rows if r["hist"]]
    rep = {"prereg_sha256_prefix": "98f52c0d32d738b1", "k": K, "train_units": len(train),
           "main_agency_history": score(main_sel),
           "two_provinces_agency_history": score([r for r in main_sel if r["prov"] in pc.START]),
           "all_test_units": score(rows),
           "by_task": {":".join(t): score([r for r in main_sel if r["task"] == t]) for t in TASKS}}
    m = rep["main_agency_history"]
    rep["verdict"] = ("方向报告（单元 < 100）" if m["units"] < 100 else
                      "采纳：本机关有历史时用分层分布" if m["H_minus_N"]["diff"] >= 0.05 and m["H_minus_N"]["ci95"][0] > 0 else
                      "未通过：维持全国分布")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

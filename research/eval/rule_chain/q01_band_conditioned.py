"""Q-01：档内数额按"省份 × 种类 / 省份 × 规则档位"条件化 vs 全国按种类（预注册
$DATA/engine/development/q01-band-conditioned-20261028/PREREG.md，sha256 前缀 4ed0624f38ab58e0）。

A1：v5 两省记录上比较 N（全国 × 种类）与 P（省份 × 种类，向 N 收缩）。
A2：两省人工要素记录（唯一档位且种类与历史一致）上再比较 B（省份 × 规则档位，向 P 收缩）。
只运行一次：python q01_band_conditioned.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402

OUT = pc.ROOT / "engine/development/q01-band-conditioned-20261028"
TASKS = [("罚款", "fine"), ("拘留", "detention_days"), ("拘留并处罚款", "detention_days"), ("拘留并处罚款", "fine")]
LEGAL = {("罚款", "fine"): (0.01, 500), ("拘留", "detention_days"): (1, 5),
         ("拘留并处罚款", "detention_days"): (10, 15), ("拘留并处罚款", "fine"): (500, 3000)}
K = 10
SENS_K = (0, 30)
FOLDS = 5
SEED = 20261028


def legal(task, v):
    lo, hi = LEGAL[task]
    return v is not None and lo <= v <= hi


def freq(units, task):
    """加权取值频率（只计法定范围内的取值）→ {值: 权重}，总权重。"""
    c = Counter()
    for u in units:
        if u["task"] == task and legal(task, u["y"]):
            c[u["y"]] += u["w"]
    return c, sum(c.values())


def shrink(cell, total, parent, k):
    keys = set(cell) | set(parent)
    if total + k == 0:
        return dict(parent)
    return {v: (cell.get(v, 0.0) + k * parent.get(v, 0.0)) / (total + k) for v in keys}


def normalize(c):
    t = sum(c.values())
    return {v: x / t for v, x in c.items()} if t else {}


def top2(dist, national):
    order = sorted(dist, key=lambda v: (-round(dist[v], 12), -national.get(v, 0.0), v))
    return order[:2]


# ---------- 数据 ----------

def pool_units():
    """v5 train 中 2026 年前、三类种类的每个目标单元。"""
    ctx = {r["id"]: r for r in pc.jl(pc.CTX)}
    rows = [r for r in pc.jl(pc.TRAIN)]
    size = Counter(r["event_id"] for r in rows)
    units = []
    for r in rows:
        x = ctx.get(r["id"], {})
        dd = pc.to_date(x.get("decision_date"))
        t = r["target"]["type"]
        if dd is None or dd.year >= 2026:
            continue
        for task in TASKS:
            if task[0] == t and r["target"].get(task[1]) is not None:
                units.append({"id": r["id"], "event": r["event_id"], "agency": x.get("authority_id") or r["id"],
                              "text": r["input"]["facts_text"], "prov": pc.province(x.get("province_code"), x.get("authority_id")),
                              "task": task, "y": float(r["target"][task[1]]), "w": 1 / size[r["event_id"]]})
    return units


def band_key(c):
    """A2：唯一档位且种类与历史一致时返回 (省份, 行为类型, 档位, 路径)，否则 None。"""
    f = c["facts"]
    st = pc.assess(f, pc.LIB).stake_threshold
    idx = st.get("observed_band_indices") or []
    types = pc.band_types(st)
    if len(idx) != 1 or idx[0] < 1 or types != [c["historical"]]:
        return None
    rule = pc.LIB.provinces[c["province"]]["rules"][f.behavior_type]
    used = st.get("measures_used") or []
    if any(e["text"] in used for e in rule.get("elevate") or []):
        path = "升档"
    elif c["province"] == "320000" and f.behavior_type == "参与赌博":
        if f.method in pc.CAT1_METHODS or f.gambling_form in ("聚众赌博", "赌场赌博"):
            path = "类一"
        elif f.gambling_form == "其他":
            path = "类二"
        else:
            path = "类别未定"
    else:
        path = "数额"
    return (c["province"], f.behavior_type, idx[0], path)


def element_units(by_id):
    cases, audit = pc.load_cases("dev", by_id)
    ctx = {r["id"]: r for r in pc.jl(pc.CTX)}
    silver = {r["id"]: r for r in pc.jl(pc.SILVER)}
    units = []
    for c in cases:
        if c["scope"] != "in_scope":
            continue
        key = band_key(c)
        audit["unique_band_type_match" if key else "not_unique_or_mismatch"] += 1
        if key is None:
            continue
        if c["id"] in silver:
            s = silver[c["id"]]
            target, agency = s["observed_outcome"], s["metadata"].get("authority") or c["id"]
        else:
            target, agency = by_id[c["id"]]["target"], ctx[c["id"]].get("authority_id") or c["id"]
        for task in TASKS:
            if task[0] == c["historical"] and target.get(task[1]) is not None:
                units.append({"id": c["id"], "event": c["event_id"], "agency": agency, "text": c["facts_text"],
                              "prov": c["province"], "task": task, "y": float(target[task[1]]), "key": key})
    ev_n = defaultdict(set)
    for u in units:
        ev_n[u["event"]].add(u["id"])
    for u in units:
        u["w"] = 1 / len(ev_n[u["event"]])
    return units, audit


# ---------- 评估 ----------

def train_pool(pool, test, axis):
    ids = {u["id"] for u in test}
    events = {u["event"] for u in test}
    texts = {u["text"] for u in test}
    agencies = {u["agency"] for u in test}
    return [u for u in pool if u["id"] not in ids and u["event"] not in events and u["text"] not in texts
            and (axis != "agency" or u["agency"] not in agencies)]


def predict(test_units, pool, elem_pool, axis, ks):
    """返回 {模型名: [(众数, 前2), ...]}，与 test_units 对齐。"""
    tp = train_pool(pool, test_units, axis)
    te = train_pool(elem_pool, test_units, axis) if elem_pool is not None else []
    cache, out = {}, defaultdict(list)
    for u in test_units:
        task, prov = u["task"], u["prov"]
        if ("N", task) not in cache:
            cache[("N", task)] = normalize(freq(tp, task)[0])
        nat = cache[("N", task)]
        out["N"].append(top2(nat, nat))
        for k in ks:
            ck = ("P", task, prov)
            if ck not in cache:
                cache[ck] = freq([x for x in tp if x["prov"] == prov], task)
            cell, tot = cache[ck]
            p = shrink(cell, tot, nat, k)
            name = "P" if k == K else f"P_k{k}"
            out[name].append(top2(p, nat))
            if elem_pool is not None:
                bk = ("B", task, u["key"])
                if bk not in cache:
                    cache[bk] = freq([x for x in te if x["key"] == u["key"]], task)
                bcell, btot = cache[bk]
                out["B" if k == K else f"B_k{k}"].append(top2(shrink(bcell, btot, p, k), nat))
    return out


def boot(a, b, events, draws=2000, seed=SEED):
    g = defaultdict(list)
    for i, e in enumerate(events):
        g[e].append(i)
    units = list(g.values())
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(draws):
        s = [i for j in rng.integers(0, len(units), len(units)) for i in units[j]]
        d.append(a[s].mean() - b[s].mean())
    return [round(float(x), 3) for x in np.quantile(d, [0.025, 0.975])]


def evaluate(units, pool, elem_pool, axis):
    groups = [u["agency"] if axis == "agency" else u["event"] for u in units]
    preds = defaultdict(lambda: [None] * len(units))
    ks = (K,) + SENS_K
    for _, te in GroupKFold(n_splits=FOLDS).split(units, groups=groups):
        test = [units[i] for i in te]
        got = predict(test, pool, elem_pool, axis, ks)
        for name, lst in got.items():
            for i, p in zip(te, lst):
                preds[name][i] = p
    y = np.array([u["y"] for u in units])
    events = [u["event"] for u in units]

    def scores(sel):
        res = {}
        hits = {}
        for name, lst in preds.items():
            mode = np.array([lst[i][0] for i in sel], dtype=float)
            t2 = np.array([y[i] in lst[i] for i in sel])
            h = (mode == y[sel]).astype(float)
            hits[name] = h
            res[name] = {"hit": round(float(h.mean()), 3), "top2": round(float(t2.mean()), 3),
                         "mae": round(float(np.abs(mode - y[sel]).mean()), 1)}
        ev = [events[i] for i in sel]
        res["P_minus_N"] = {"diff": round(float(hits["P"].mean() - hits["N"].mean()), 3),
                            "ci95": boot(hits["P"], hits["N"], ev)}
        if "B" in hits:
            res["B_minus_P"] = {"diff": round(float(hits["B"].mean() - hits["P"].mean()), 3),
                                "ci95": boot(hits["B"], hits["P"], ev)}
        res["units"] = len(sel)
        res["events"] = len(set(ev))
        return res

    allsel = np.arange(len(units))
    report = {"all": scores(allsel)}
    for prov in ("130000", "320000"):
        sel = np.array([i for i, u in enumerate(units) if u["prov"] == prov])
        if len(sel):
            report[prov] = scores(sel)
    for task in TASKS:
        sel = np.array([i for i, u in enumerate(units) if u["task"] == task])
        if len(sel):
            report[":".join(task)] = scores(sel)
    return report


def main():
    by_id = {r["id"]: r for r in pc.jl(pc.TRAIN)}
    pool = pool_units()
    a1 = [u for u in pool if u["prov"] in pc.START]
    elem, audit = element_units(by_id)
    report = {"prereg_sha256_prefix": "4ed0624f38ab58e0", "k": K, "folds": FOLDS,
              "a1": {"units": len(a1), "records": len({u["id"] for u in a1}), "events": len({u["event"] for u in a1}),
                     "agencies": len({u["agency"] for u in a1}),
                     **{axis: evaluate(a1, pool, None, axis) for axis in ("agency", "event")}},
              "a2": {"audit": dict(audit), "units": len(elem), "records": len({u["id"] for u in elem}),
                     "agencies": len({u["agency"] for u in elem}),
                     "keys": Counter("|".join(map(str, u["key"])) for u in elem).most_common(),
                     **{axis: evaluate(elem, pool, elem, axis) for axis in ("agency", "event")}}}
    a1g, a2g = report["a1"]["agency"]["all"], report["a2"]["agency"]["all"]
    report["verdict"] = {
        "A1": ("方向报告（单元 < 200）" if a1g["units"] < 200 else
               "省份条件化可迁移" if a1g["P_minus_N"]["diff"] >= 0.05 and a1g["P_minus_N"]["ci95"][0] > 0 else
               "机关习惯（只事件轴）" if (lambda e: e["diff"] >= 0.05 and e["ci95"][0] > 0)(report["a1"]["event"]["all"]["P_minus_N"]) else
               "未通过：维持全国 × 种类"),
        "A2": ("方向报告（单元 < 60）" if a2g["units"] < 60 else
               "规则档位细分有增益" if a2g["B_minus_P"]["diff"] >= 0.05 and a2g["B_minus_P"]["ci95"][0] > 0 else
               "未通过：规则档位细分无额外增益")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), "utf-8")
    print(json.dumps(report["verdict"], ensure_ascii=False))
    for part in ("a1", "a2"):
        for axis in ("agency", "event"):
            r = report[part][axis]["all"]
            print(part, axis, {k: v for k, v in r.items() if k in ("N", "P", "B", "P_minus_N", "B_minus_P", "units", "events")})


if __name__ == "__main__":
    main()

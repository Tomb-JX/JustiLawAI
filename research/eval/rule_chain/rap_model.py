"""规则锚定的实务模型（RAP）：C 层规则结论作锚点，E 层学"规则这样说时实际怎么罚"。

预注册 $DATA/engine/development/rap-20261028/PREREG.md。
  python rap_model.py dev    # 开发集事件分组 5 折交叉验证（开发参考）
  python rap_model.py test   # 工单 B 新数据，只运行一次
对照：引擎第一版（规则唯一 → 规则；多候选 → 文本在候选内；无分档 → 文本）与纯文本。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402

OUT = pc.ROOT / "engine/development/rap-20261028"
ORDER = pc.ORDER
SEED = 20261028
NETWORK = {"网络赌博"}
MACHINE = {"赌博机"}
LOTTERY = {"私彩", "六合彩", "赌球"}


def tri(v):
    return (1.0, 0.0) if v is True else (0.0, 1.0) if v is None else (0.0, 0.0)


def amount_mid(a):
    if a is None:
        return None
    d = a.model_dump()
    lo, hi = d.get("min"), d.get("max")
    if lo is None and hi is None:
        return None
    return lo if hi is None else hi if lo is None else (lo + hi) / 2


def features(c, text_proba):
    """部署时可得的输入：规则结论、结构化要素、文本概率。不使用任何由处罚结果反推的量。"""
    f = c["facts"]
    types = pc.band_types(pc.assess(f, pc.LIB).stake_threshold)
    x = []
    for t in ORDER:                                   # 规则锚点
        x += [float(types == [t]), float(len(types) > 1 and t in types)]
    x += [float(not types), float(c["province"] == "130000"), float(f.behavior_type == "为赌博提供条件")]
    m = f.method
    x += [float(m in NETWORK), float(m in MACHINE), float(m in LOTTERY), float(m is None)]
    x += [*tri(f.civil_servant), *tri(_venue_public(f))]
    for field in ("personal_stake", "onsite_stake_total", "commission"):
        v = amount_mid(getattr(f, field, None))
        x += [math.log10(v + 1) if v is not None else 0.0, float(v is None)]
    n = f.participant_count
    x += [math.log(n) if n else 0.0, float(not n)]
    x += [math.log(max(text_proba.get(t, 0.0), 1e-4)) for t in ORDER]   # 文本证据
    return np.array(x), types


def _venue_public(f):
    v = getattr(f, "venue_type", None)
    return None if v is None else v in ("公共场所", "交通工具")


def v1_dist(types, proba):
    if len(types) == 1:
        return {t: float(t == types[0]) for t in ORDER}
    keep = types or ORDER
    z = sum(proba.get(t, 0.0) for t in keep) or 1.0
    return {t: (proba.get(t, 0.0) / z if t in keep else 0.0) for t in ORDER}


def fit(X, y):
    sc = StandardScaler().fit(X)
    lr = LogisticRegression(C=1.0, max_iter=5000, random_state=SEED)
    lr.fit(sc.transform(X), y)
    return lambda Z: [dict(zip(lr.classes_, p)) for p in lr.predict_proba(sc.transform(Z))]


def score(rows):
    out = {"n": len(rows)}
    for name in ("rap", "v1", "text"):
        out[name] = {"rps": round(float(np.mean([pc.rps({t: r[name].get(t, 0.0) for t in ORDER}, r["truth"]) for r in rows])), 4),
                     "acc": round(float(np.mean([max(r[name], key=r[name].get) == r["truth"] for r in rows])), 3)}
    return out


def boot(rows, a, b, draws=2000):
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(r["event"], []).append(i)
    units = list(groups.values())
    d_a = np.array([pc.rps({t: r[a].get(t, 0.0) for t in ORDER}, r["truth"]) for r in rows])
    d_b = np.array([pc.rps({t: r[b].get(t, 0.0) for t in ORDER}, r["truth"]) for r in rows])
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(draws):
        s = [i for j in rng.integers(0, len(units), len(units)) for i in units[j]]
        diffs.append(d_a[s].mean() - d_b[s].mean())
    return [round(float(q), 4) for q in np.quantile(diffs, [0.025, 0.975])], round(float(d_a.mean() - d_b.mean()), 4)


def report(rows):
    ci, diff = boot(rows, "rap", "v1")
    rep = {"all": score(rows), "rap_minus_v1_rps": diff, "ci95": ci}
    for p in ("130000", "320000"):
        rep[p] = score([r for r in rows if r["province"] == p])
    for route in ("single", "candidates", "none"):
        sel = [r for r in rows if r["route"] == route]
        if sel:
            rep["route_" + route] = score(sel)
    sel = [r for r in rows if r["network"]]
    if sel:
        rep["network"] = score(sel)
    return rep


def build(cases, probas):
    X, meta = [], []
    for c, p in zip(cases, probas):
        x, types = features(c, p)
        X.append(x)
        meta.append({"id": c["id"], "event": c["event_id"], "province": c["province"], "truth": c["historical"],
                     "route": "single" if len(types) == 1 else "candidates" if types else "none",
                     "network": c["facts"].method in NETWORK, "v1": v1_dist(types, p), "text": p})
    return np.array(X), meta


def main():
    mode = sys.argv[1]
    train = pc.jl(pc.TRAIN)
    by_id = {r["id"]: r for r in train}
    dev, _ = pc.load_cases("dev", by_id)
    test, audit = pc.load_cases("test", by_id) if mode == "test" else ([], {})
    predict, _ = pc.text_model(train, dev + test)
    dev_in = [c for c in dev if c["scope"] == "in_scope"]
    Xd, md = build(dev_in, predict([c["facts_text"] for c in dev_in]))
    yd = np.array([c["historical"] for c in dev_in])
    if mode == "dev":
        groups = [c["event_id"] for c in dev_in]
        for tr, va in GroupKFold(n_splits=5).split(Xd, yd, groups):
            pred = fit(Xd[tr], yd[tr])(Xd[va])
            for i, p in zip(va, pred):
                md[i]["rap"] = {t: float(p.get(t, 0.0)) for t in ORDER}
        rows = md
    else:
        dev_events = {c["event_id"] for c in dev}
        cases = [c for c in test if c["scope"] == "in_scope" and c["event_id"] not in dev_events]
        Xt, rows = build(cases, predict([c["facts_text"] for c in cases]))
        for r, p in zip(rows, fit(Xd, yd)(Xt)):
            r["rap"] = {t: float(p.get(t, 0.0)) for t in ORDER}
    rep = {"mode": mode, "audit": dict(audit), **report(rows)}
    if mode == "test":
        rep["verdict"] = ("样本不足（< 60），只报方向" if rep["all"]["n"] < 60 else
                          "RAP 优于第一版" if rep["ci95"][1] < 0 else "未优于第一版")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"report_{mode}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

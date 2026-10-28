"""新数据（工单 B）准确率低的分层诊断：错在 C 层定档，还是 D/E 层实务模型？（描述性，标签此前已看过，不是检验）

  python diagnose_newdata.py

对开发集（事件 5 折交叉验证）与工单 B（开发集全量训练）用同一口径拆：
- 路由：规则唯一 / 多候选 / 无分档，各自占比；
- 规则唯一：成文种类 = 实际处罚的比例（C 层对、但实务偏离的有多少）；
- 多候选：实际处罚落在候选内的比例（覆盖），候选内 RAP 选对的比例；
- 无分档：为什么定不了（缺哪项要素 / 哪类状态），RAP 在其中的准确率；
- 标签分布、各省构成、关键要素缺失率。
输出 $DATA/engine/development/diagnose-newdata-20261028/report.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402
import rap_export as rx  # noqa: E402
from app.discretion import trace as tr  # noqa: E402

OUT = pc.ROOT / "engine/development/diagnose-newdata-20261028"
ORDER = rx.ORDER


def route(types):
    return "single" if len(types) == 1 else "candidates" if types else "none"


def rows_of(cases, ds):
    rows = []
    for c, d in zip(cases, ds):
        f = c["facts"]
        st = pc.assess(f, pc.LIB).stake_threshold
        types = pc.band_types(st)
        pred = max(d, key=d.get)
        rows.append({"id": c["id"], "province": c["province"], "truth": c["historical"], "route": route(types),
                     "types": types, "rap": pred, "rap_p_truth": round(d.get(c["historical"], 0.0), 3),
                     "method": f.method, "behavior": f.behavior_type, "status": st.get("status"),
                     "missing": [m["field"] for m in tr.missing(st)],
                     "has_personal": f.personal_stake is not None, "has_onsite": f.onsite_stake_total is not None})
    return rows


def acc(rows, key="rap"):
    return round(float(np.mean([r[key] == r["truth"] for r in rows])), 3) if rows else None


def summarize(rows):
    out = {"n": len(rows), "rap_acc": acc(rows),
           "province": dict(Counter(r["province"] for r in rows)),
           "labels": dict(Counter(r["truth"] for r in rows)),
           "missing_personal_stake": round(float(np.mean([not r["has_personal"] for r in rows])), 3),
           "missing_both_stakes": round(float(np.mean([not r["has_personal"] and not r["has_onsite"] for r in rows])), 3)}
    for rt in ("single", "candidates", "none"):
        sel = [r for r in rows if r["route"] == rt]
        part = {"n": len(sel), "share": round(len(sel) / len(rows), 3), "rap_acc": acc(sel),
                "labels": dict(Counter(r["truth"] for r in sel)),
                "majority_acc": round(Counter(r["truth"] for r in sel).most_common(1)[0][1] / len(sel), 3) if sel else None}
        if rt == "single":
            ok = [r for r in sel if r["types"][0] == r["truth"]]
            part["rule_acc"] = round(len(ok) / len(sel), 3) if sel else None
            part["rule_vs_truth"] = dict(Counter(f"{r['types'][0]}→{r['truth']}" for r in sel if r["types"][0] != r["truth"]))
        if rt == "candidates":
            cov = [r for r in sel if r["truth"] in r["types"]]
            part["coverage"] = round(len(cov) / len(sel), 3) if sel else None
            part["rap_acc_when_covered"] = acc(cov)
            part["candidate_sets"] = dict(Counter("/".join(r["types"]) for r in sel))
        if rt == "none":
            part["why"] = dict(Counter(r["status"] for r in sel))
            part["missing_fields"] = dict(Counter(m for r in sel for m in r["missing"]))
            part["methods"] = dict(Counter(r["method"] for r in sel))
        out[rt] = part
    for p in ("130000", "320000"):
        sel = [r for r in rows if r["province"] == p]
        out[f"by_province_{p}"] = {"n": len(sel), "rap_acc": acc(sel),
                                   "routes": dict(Counter(r["route"] for r in sel))}
    return out


def main():
    train = pc.jl(pc.TRAIN)
    by_id = {r["id"]: r for r in train}
    dev, _ = pc.load_cases("dev", by_id)
    dev = [c for c in dev if c["scope"] == "in_scope"]
    test, _ = pc.load_cases("test", by_id)
    dev_events = {c["event_id"] for c in dev}
    test = [c for c in test if c["scope"] == "in_scope" and c["event_id"] not in dev_events]
    Xd, yd = rx.matrix(dev)
    Xt, _ = rx.matrix(test)
    cv = [None] * len(yd)
    for tr_i, va in GroupKFold(n_splits=5).split(Xd, yd, [c["event_id"] for c in dev]):
        sc, lr = rx.fit(Xd[tr_i], yd[tr_i])
        for i, d in zip(va, rx.dists(sc, lr, Xd[va])):
            cv[i] = d
    sc, lr = rx.fit(Xd, yd)
    rep = {"note": "描述性诊断：工单 B 标签此前已看过，不作检验",
           "dev_cv": summarize(rows_of(dev, cv)), "workorder_b": summarize(rows_of(test, rx.dists(sc, lr, Xt)))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""RAP v2：规则生成特征（ADR-011），开发集 + 工单 B 训练（连续任务 P3）。

  python rap_v2.py

- 训练集：开发集在范围内 391 + 工单 B 84（排除与开发集同事件）；规则为当前版本（含累计赌资与 P1 补编）；
- 开发性比较（描述，不作判定）：事件 5 折、机关 5 折下，v1 手工特征 / v2 规则特征 / 只用规则结论 / 边际分布；
- 全量训练 v2，导出 justilaw-api/app/discretion/data/rap-ruled-v2.json（不依赖 sklearn）；线上默认仍为 v1。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402
from app.discretion import practice, rule_features  # noqa: E402

API = Path(__file__).resolve().parents[3] / "justilaw-api"
OUT = API / "app/discretion/data/rap-ruled-v2.json"
OUT_RULE_ONLY = API / "app/discretion/data/rap-ruleonly-v2.json"
REPORT = pc.ROOT / "engine/development/rap-v2-20261028"
ORDER = practice.ORDER
SEED = 20261028
N_RULE = 9          # 规则生成特征的前 9 维 = 规则结论


def load():
    train = pc.jl(pc.TRAIN)
    by_id = {r["id"]: r for r in train}
    dev, _ = pc.load_cases("dev", by_id)
    dev = [c for c in dev if c["scope"] == "in_scope"]
    ev = {c["event_id"] for c in dev}
    test, _ = pc.load_cases("test", by_id)
    b = [c for c in test if c["scope"] == "in_scope" and c["event_id"] not in ev]
    for c in dev:
        c["split"] = "dev"
    for c in b:
        c["split"] = "workorder_b"
    return dev + b


def mats(cases):
    v1 = np.array([practice.features(c["facts"], pc.types_of(c["facts"]), c["province"]) for c in cases])
    v2 = np.array([rule_features.features(c["facts"]) for c in cases])
    y = np.array([c["historical"] for c in cases])
    return {"v1_manual": v1, "v2_rule": v2, "rule_only": v2[:, :N_RULE]}, y


def fit(X, y):
    sc = StandardScaler().fit(X)
    lr = LogisticRegression(C=1.0, max_iter=5000, random_state=SEED).fit(sc.transform(X), y)
    return sc, lr


def dists(sc, lr, X):
    return [{t: float(dict(zip(lr.classes_, p)).get(t, 0.0)) for t in ORDER} for p in lr.predict_proba(sc.transform(X))]


def score(ds, y):
    pred = [max(d, key=d.get) for d in ds]
    rec = {}
    for t in ORDER:
        sel = [p for p, tt in zip(pred, y) if tt == t]
        if sel:
            rec[t] = round(sum(p == t for p in sel) / len(sel), 3)
    return {"n": len(y), "rps": round(float(np.mean([pc.rps(d, t) for d, t in zip(ds, y)])), 4),
            "acc": round(float(np.mean([p == t for p, t in zip(pred, y)])), 3), "recall": rec}


def cv(Xs, y, groups):
    out = {}
    for name, X in Xs.items():
        pred = [None] * len(y)
        for tr, va in GroupKFold(n_splits=5).split(X, y, groups):
            sc, lr = fit(X[tr], y[tr])
            for i, d in zip(va, dists(sc, lr, X[va])):
                pred[i] = d
        out[name] = score(pred, y)
    marg = [None] * len(y)
    for tr, va in GroupKFold(n_splits=5).split(y, y, groups):
        cnt = Counter(y[tr])
        d = {t: (cnt.get(t, 0) + 0.5) / (len(tr) + 2) for t in ORDER}
        for i in va:
            marg[i] = d
    out["marginal"] = score(marg, y)
    return out


def main():
    cases = load()
    Xs, y = mats(cases)
    events = [c["event_id"] for c in cases]
    agencies = [(c["event_id"] or "").split("|")[0] for c in cases]
    spec = list(rule_features.spec())
    active = int((Xs["v2_rule"] != 0).any(axis=0).sum())
    rep = {"n": len(y), "by_split": dict(Counter(c["split"] for c in cases)), "labels": dict(Counter(y)),
           "rule_features": {"total": len(spec), "nonzero_in_training": active},
           "cv_event_5fold": cv(Xs, y, events), "cv_agency_5fold": cv(Xs, y, agencies)}
    sc, lr = fit(Xs["v2_rule"], y)
    ids = sorted(c["id"] for c in cases)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=Path(__file__).parent).stdout.strip()
    model = {
        "version": "rap-ruled-v2", "feature_set": "rule", "spec_hash": rule_features.spec_hash(),
        "trained": date.today().isoformat(), "features": [s["name"] for s in spec],
        "classes": [str(k) for k in lr.classes_], "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
        "coef": lr.coef_.tolist(), "intercept": lr.intercept_.tolist(),
        "training": {"n": len(y), "by_split": rep["by_split"], "label_counts": {t: int((y == t).sum()) for t in ORDER},
                     "source": "两省人工要素：开发集 391 + 工单 B 84；规则含累计赌资与 P1 补编（ADR-011 规则生成特征）",
                     "ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
                     "algorithm": "StandardScaler + 多项逻辑回归（C=1，lbfgs）",
                     "script": f"research/eval/rule_chain/rap_v2.py@{commit}"},
        "evaluation": {"dev_cv_event_5fold": rep["cv_event_5fold"]["v2_rule"],
                       "dev_cv_agency_5fold": rep["cv_agency_5fold"]["v2_rule"],
                       "note": "开发性描述；独立检验见工单 C 预注册"},
        "limits": ["实务参照，不是法律结论", "只在河北、江苏两省人工要素上训练", "规则变更后须重训（特征名单哈希校验）",
                   "训练集不予处罚极少"],
    }
    OUT.write_text(json.dumps(model, ensure_ascii=False, indent=1), "utf-8")
    # 只用规则结论（规则生成特征的前 9 维）：开发集两种分组下 RPS 最低，作为工单 C 预注册的主候选
    sc2, lr2 = fit(Xs["rule_only"], y)
    ro = {**model, "version": "rap-ruleonly-v2", "features": [s["name"] for s in spec[:N_RULE]],
          "classes": [str(k) for k in lr2.classes_], "mean": sc2.mean_.tolist(), "scale": sc2.scale_.tolist(),
          "coef": lr2.coef_.tolist(), "intercept": lr2.intercept_.tolist(),
          "evaluation": {"dev_cv_event_5fold": rep["cv_event_5fold"]["rule_only"],
                         "dev_cv_agency_5fold": rep["cv_agency_5fold"]["rule_only"],
                         "note": "开发性描述；独立检验见工单 C 预注册"}}
    OUT_RULE_ONLY.write_text(json.dumps(ro, ensure_ascii=False, indent=1), "utf-8")
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "report_dev.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

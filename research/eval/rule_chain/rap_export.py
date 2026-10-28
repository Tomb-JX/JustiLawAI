"""导出 RAP 无文本版参数供线上引擎使用（Q-23、ADR-009）。

  python rap_export.py

- 特征由 app.discretion.practice.features 计算（线上同一函数），并逐条核对与 rap_model.features 去掉文本列后一致；
- 训练集 = 开发集两省人工要素在范围内的记录（与 C-37 相同，不含工单 B）；
- 附开发集事件 5 折交叉验证与工单 B 的描述性数字。工单 B 的标签此前已被看过（C-40、C-41），
  这里的数字只是描述，不是预注册检验；独立检验留给下一批新要素数据。
输出：justilaw-api/app/discretion/data/rap-notext-v1.json
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402
import rap_model as rm  # noqa: E402
from app.discretion import practice  # noqa: E402  prob_chain 已把 justilaw-api 加入路径

OUT = Path(__file__).resolve().parents[3] / "justilaw-api/app/discretion/data/rap-notext-v1.json"
ORDER = practice.ORDER


def matrix(cases):
    X = []
    for c in cases:
        types = pc.types_of(c["facts"])
        x = practice.features(c["facts"], types, c["province"])
        ref, _ = rm.features(c, {})
        assert np.allclose(x, ref[:len(x)]) and len(ref) == len(x) + len(ORDER), c["id"]
        X.append(x)
    return np.array(X), np.array([c["historical"] for c in cases])


def fit(X, y):
    sc = StandardScaler().fit(X)
    lr = LogisticRegression(C=1.0, max_iter=5000, random_state=rm.SEED).fit(sc.transform(X), y)
    return sc, lr


def dists(sc, lr, X):
    return [{t: float(dict(zip(lr.classes_, p)).get(t, 0.0)) for t in ORDER} for p in lr.predict_proba(sc.transform(X))]


def metrics(ds, y):
    pred = [max(d, key=d.get) for d in ds]
    out = {"n": len(y), "rps": round(float(np.mean([pc.rps(d, t) for d, t in zip(ds, y)])), 4),
           "acc": round(float(np.mean([p == t for p, t in zip(pred, y)])), 3), "recall": {}}
    for t in ORDER:
        sel = [p for p, tt in zip(pred, y) if tt == t]
        if sel:
            out["recall"][t] = {"n": len(sel), "recall": round(sum(p == t for p in sel) / len(sel), 3)}
    return out


def main():
    train = pc.jl(pc.TRAIN)
    by_id = {r["id"]: r for r in train}
    dev, _ = pc.load_cases("dev", by_id)
    dev = [c for c in dev if c["scope"] == "in_scope"]
    test, _ = pc.load_cases("test", by_id)
    dev_events = {c["event_id"] for c in dev}
    test = [c for c in test if c["scope"] == "in_scope" and c["event_id"] not in dev_events]
    Xd, yd = matrix(dev)
    Xt, yt = matrix(test)

    cv = [None] * len(yd)
    for tr, va in GroupKFold(n_splits=5).split(Xd, yd, [c["event_id"] for c in dev]):
        sc, lr = fit(Xd[tr], yd[tr])
        for i, d in zip(va, dists(sc, lr, Xd[va])):
            cv[i] = d
    sc, lr = fit(Xd, yd)
    ids = sorted(c["id"] for c in dev)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=Path(__file__).parent).stdout.strip()
    model = {
        "version": "rap-notext-v1",
        "trained": date.today().isoformat(),
        "features": [s["name"] for s in practice.feature_spec()],
        "classes": [str(k) for k in lr.classes_],
        "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
        "coef": lr.coef_.tolist(), "intercept": lr.intercept_.tolist(),
        "training": {"n": len(yd), "label_counts": {t: int((yd == t).sum()) for t in ORDER},
                     "source": "开发集两省人工要素（331 会话标注 + 66 银标，校验通过、范围内）；规则按 ADR-008",
                     "ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
                     "algorithm": "StandardScaler + 多项逻辑回归（C=1，lbfgs）",
                     "script": f"research/eval/rule_chain/rap_export.py@{commit}"},
        "evaluation": {"dev_cv_event_5fold": metrics(cv, yd),
                       "workorder_b_descriptive": {**metrics(dists(sc, lr, Xt), yt),
                                                   "note": "标签此前已看过（C-40、C-41），只作描述，不是预注册检验"},
                       "frozen_test_reference": "含文本 RAP 冻结检验 C-37：RPS 0.154 vs 第一版 0.196"},
        "limits": ["实务参照，不是法律结论", "只在河北、江苏两省人工要素上训练；要素由模型抽取时表现未检验",
                   "无文本版未经独立预注册检验", "拘留召回偏弱，不予处罚样本极少"],
    }
    OUT.write_text(json.dumps(model, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: model[k] for k in ("classes", "training", "evaluation")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

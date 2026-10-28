"""档内要素学习能否实现（Q-27）：以实际处罚种类为条件，预测法定档内落在哪个锚点值。

预注册：$DATA/engine/development/within-band-elements-20261028/PREREG.md
  python within_band_elements.py units   # 只数样本与锚点映射（不看要素与数额的关系）
  python within_band_elements.py dev     # 第一阶段：开发集 + 工单 B，按机关留出 5 折 + 时间外推 + 方差分解，只跑一次
  python within_band_elements.py heldout # 第二阶段：全量训练冻结模型，在工单 C 上检验（工单 C 交回后）

四个部分（单元）：罚款档罚款额、拘留档天数、并处档天数、并处档罚款额。
锚点：引擎现行全国分布（band_quantities.json）中占比 ≥ 3% 的取值；实际值映射到最近锚点（等距取较小者）。
模型：
  M0  引擎现行：全国分布按本案法定幅度过滤后映射到锚点（decide._legal_distribution）
  M0b 训练折内边际分布（同训练数据、不用要素）
  M1  要素多项逻辑回归（标准化，L2，C=1，不调参）——主模型
  M3  梯度提升树（深度 3、100 轮、L2=1、叶最少 10 条）——非线性上限对照
所有模型输出统一做 ε=0.01 均匀平滑。主指标：有序锚点上的 RPS。
"""
from __future__ import annotations

import ast
import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402
from app.discretion import decide as dc  # noqa: E402
from app.discretion import practice  # noqa: E402

OUT = pc.ROOT / "engine/development/within-band-elements-20261028"
SEED, EPS, MIN_SHARE = 20261028, 0.01, 0.03
COMPONENTS = [("罚款", "fine"), ("拘留", "detention_days"), ("拘留并处罚款", "detention_days"), ("拘留并处罚款", "fine")]
CUT = date(2023, 1, 1)                       # 时间外推：决定日期 < 2023 训练，≥ 2023 检验
Q = json.loads((Path(dc.__file__).parent / "data/band_quantities.json").read_text("utf-8"))


def anchors(kind, field):
    return sorted(v for v, s in Q["bands"][kind][field]["values"] if s >= MIN_SHARE)


def snap(v, anc):
    return min(range(len(anc)), key=lambda i: (abs(anc[i] - v), anc[i]))


# ---------- 特征（全部是部署时可得的要素；不含任何由结果反推的量） ----------

def tri(v):
    return (1.0, 0.0) if v is True else (0.0, 1.0) if v is None else (0.0, 0.0)


def logamt(a):
    v = practice._amount_mid(a)
    return (math.log10(v + 1), 0.0) if v is not None else (0.0, 1.0)


def features(c):
    f = c["facts"]
    st = pc.assess(f, pc.LIB).stake_threshold
    hi = st.get("observed_band_indices") or []
    x = practice.features(f, pc.band_types(st), c["province"])          # 规则结论 + RAP 的要素组
    x += [float(len(hi) == 1 and i in hi) for i in range(1, 4)]          # 唯一档位序号
    x += [*logamt(f.cumulative_stake)]
    for v in (f.first_offense, f.admits_and_accepts, f.truthful_statement, f.surrendered,
              f.remedied_consequence, f.coerced_or_lured, f.minors_involved, f.profit_purpose):
        x += [*tri(v)]
    x += [float(f.minor_circumstance is not None), float(f.violations_last_year or 0) > 0,
          float(f.violations_last_year is None)]
    t = f.times
    x += [math.log(t) if t else 0.0, float(not t)]
    age = f.age
    x += [float(age is not None and age < 18), float(age is not None and age >= 60), float(age is None)]
    return x


# ---------- 数据 ----------

def target_of(rec):
    t = rec["target"]
    return t if isinstance(t, dict) else ast.literal_eval(t)


def load(split_names=("dev", "test")):
    train = pc.jl(pc.TRAIN)
    by_id = {r["id"]: r for r in train}
    out, seen_events = [], set()
    for split in split_names:
        cases, _ = pc.load_cases(split, by_id)
        for c in cases:
            if c["scope"] != "in_scope" or c["event_id"] in (seen_events if split == "test" else ()):
                continue
            if split == "dev":
                seen_events.add(c["event_id"])
            tgt = target_of(by_id[c["id"]]) if c["id"] in by_id else None
            if not tgt:
                continue
            c["target_amounts"] = tgt
            c["agency"] = (c["event_id"] or "").split("|")[0] or c["id"]
            c["split"] = split
            out.append(c)
    return out


def units(cases):
    rows = {comp: [] for comp in COMPONENTS}
    for c in cases:
        for kind, field in COMPONENTS:
            if c["historical"] != kind:
                continue
            v = c["target_amounts"].get(field)
            if not v:
                continue
            anc = anchors(kind, field)
            rows[(kind, field)].append({"case": c, "y": snap(float(v), anc), "value": float(v)})
    return rows


# ---------- 模型 ----------

def smooth(p):
    return (1 - EPS) * p + EPS / len(p)


def rps(p, y):
    cp, ct = np.cumsum(p), np.cumsum(np.eye(len(p))[y])
    return float(np.sum((cp - ct)[:-1] ** 2) / (len(p) - 1))


def engine_dist(c, kind, field, anc):
    dist = dc._legal_distribution(pc.assess(c["facts"], pc.LIB), kind, field) or \
        [tuple(x) for x in Q["bands"][kind][field]["values"]]
    p = np.zeros(len(anc))
    for v, s in dist:
        p[snap(v, anc)] += s
    return p / p.sum()


def fit_predict(kind_name, Xtr, ytr, Xte, k):
    present = np.unique(ytr)
    if kind_name == "M0b":
        cnt = np.bincount(ytr, minlength=k) + 0.5
        return np.tile(cnt / cnt.sum(), (len(Xte), 1))
    if len(present) == 1:
        p = np.zeros((len(Xte), k))
        p[:, present[0]] = 1.0
        return p
    if kind_name == "M1":
        sc = StandardScaler().fit(Xtr)
        m = LogisticRegression(C=1.0, max_iter=5000, random_state=SEED).fit(sc.transform(Xtr), ytr)
        raw = m.predict_proba(sc.transform(Xte))
    else:
        m = HistGradientBoostingClassifier(max_depth=3, max_iter=100, learning_rate=0.1, l2_regularization=1.0,
                                           min_samples_leaf=10, random_state=SEED).fit(Xtr, ytr)
        raw = m.predict_proba(Xte)
    p = np.zeros((len(Xte), k))
    p[:, m.classes_] = raw
    return p


def evaluate(split_fn, rows_by_comp):
    """split_fn(rows) → [(train_idx, test_idx)]；返回逐单元记录。"""
    recs = []
    for (kind, field), rows in rows_by_comp.items():
        anc = anchors(kind, field)
        k = len(anc)
        X = np.array([features(r["case"]) for r in rows])
        y = np.array([r["y"] for r in rows])
        for tr, te in split_fn(rows):
            if len(tr) < 10 or len(te) == 0:
                continue
            preds = {m: fit_predict(m, X[tr], y[tr], X[te], k) for m in ("M0b", "M1", "M3")}
            for j, i in enumerate(te):
                c = rows[i]["case"]
                ps = {"M0": smooth(engine_dist(c, kind, field, anc)),
                      **{m: smooth(preds[m][j]) for m in preds}}
                recs.append({"component": f"{kind}:{field}", "agency": c["agency"], "province": c["province"],
                             "y": int(y[i]), **{f"rps_{m}": rps(p, int(y[i])) for m, p in ps.items()},
                             **{f"ll_{m}": float(-np.log(p[int(y[i])])) for m, p in ps.items()},
                             **{f"hit_{m}": int(np.argmax(p) == y[i]) for m, p in ps.items()}})
    return recs


def summarize(recs, draws=2000):
    out = {"n": len(recs)}
    models = ("M0", "M0b", "M1", "M3")
    for m in models:
        out[m] = {k: round(float(np.mean([r[f"{k}_{m}"] for r in recs])), 4) for k in ("rps", "ll", "hit")}
    agencies = sorted({r["agency"] for r in recs})
    idx = {a: [i for i, r in enumerate(recs) if r["agency"] == a] for a in agencies}
    rng = np.random.default_rng(SEED)
    for a, b in (("M1", "M0b"), ("M1", "M0"), ("M3", "M0b")):
        d = np.array([r[f"rps_{a}"] - r[f"rps_{b}"] for r in recs])
        boots = []
        for _ in range(draws):
            s = [i for g in rng.integers(0, len(agencies), len(agencies)) for i in idx[agencies[g]]]
            boots.append(d[s].mean())
        out[f"{a}-{b}"] = {"diff": round(float(d.mean()), 4),
                           "ci95": [round(float(q), 4) for q in np.quantile(boots, [0.025, 0.975])]}
    return out


# ---------- 方差分解：随机截距线性模型（REML，自实现） ----------

def reml_random_intercept(y, X, groups):
    """y = Xβ + u_g + e。返回 σ_u²、σ_e²、固定效应线性预测的方差。"""
    keep = X.std(axis=0) > 0
    X = np.column_stack([np.ones(len(y)), X[:, keep]])
    q, r = np.linalg.qr(X)
    X = X[:, np.abs(np.diag(r)) > 1e-8 * np.abs(np.diag(r)).max()]
    g = {k: i for i, k in enumerate(sorted(set(groups)))}
    Z = np.zeros((len(y), len(g)))
    Z[np.arange(len(y)), [g[k] for k in groups]] = 1.0
    n, p = X.shape
    ZZ = Z @ Z.T

    def neg_reml(log_lam):
        V = np.exp(log_lam) * ZZ + np.eye(n)
        Vi = np.linalg.inv(V)
        XtViX = X.T @ Vi @ X
        beta = np.linalg.solve(XtViX, X.T @ Vi @ y)
        res = y - X @ beta
        s2 = float(res @ Vi @ res) / (n - p)
        return 0.5 * ((n - p) * np.log(s2) + np.linalg.slogdet(V)[1] + np.linalg.slogdet(XtViX)[1])

    lam = float(np.exp(minimize_scalar(neg_reml, bounds=(-12, 6), method="bounded").x))
    V = lam * ZZ + np.eye(n)
    Vi = np.linalg.inv(V)
    beta = np.linalg.solve(X.T @ Vi @ X, X.T @ Vi @ y)
    res = y - X @ beta
    s2e = float(res @ Vi @ res) / (n - p)
    return {"sigma2_agency": lam * s2e, "sigma2_resid": s2e, "var_fixed": float(np.var(X @ beta)), "n": n,
            "agencies": len(g), "fixed_params": p}


def decompose(rows_by_comp):
    out = {}
    for (kind, field), rows in rows_by_comp.items():
        y = np.log(np.array([r["value"] for r in rows]))
        grp = [r["case"]["agency"] for r in rows]
        null = reml_random_intercept(y, np.zeros((len(y), 0)), grp)
        full = reml_random_intercept(y, np.array([features(r["case"]) for r in rows]), grp)
        tot_n = null["sigma2_agency"] + null["sigma2_resid"]
        tot_f = full["var_fixed"] + full["sigma2_agency"] + full["sigma2_resid"]
        out[f"{kind}:{field}"] = {
            "n": full["n"], "agencies": full["agencies"],
            "icc_agency_null": round(null["sigma2_agency"] / tot_n, 3),
            "r2_marginal_elements": round(full["var_fixed"] / tot_f, 3),
            "r2_conditional_elements_agency": round((full["var_fixed"] + full["sigma2_agency"]) / tot_f, 3),
            "residual_share": round(full["sigma2_resid"] / tot_f, 3)}
    return out


# ---------- 入口 ----------

def main():
    mode = sys.argv[1]
    if mode == "units":
        rows = units(load())
        for comp, rs in rows.items():
            print(comp, "n", len(rs), "agencies", len({r["case"]["agency"] for r in rs}), "anchors", anchors(*comp),
                  "split", dict(Counter(r["case"]["split"] for r in rs)),
                  "<2023", sum(r["case"]["dd"] < CUT for r in rs))
        return
    if mode == "dev":
        rows = units(load())

        def by_agency(rs):
            return list(GroupKFold(n_splits=5).split(np.zeros(len(rs)), groups=[r["case"]["agency"] for r in rs]))

        def by_time(rs):
            tr = [i for i, r in enumerate(rs) if r["case"]["dd"] < CUT]
            te = [i for i, r in enumerate(rs) if r["case"]["dd"] >= CUT]
            return [(np.array(tr), np.array(te))]

        rep = {"mode": "dev", "units": {f"{k}:{f}": len(v) for (k, f), v in rows.items()}}
        rec_a = evaluate(by_agency, rows)
        rep["agency_out"] = {"all": summarize(rec_a),
                             **{comp: summarize([r for r in rec_a if r["component"] == comp])
                                for comp in sorted({r["component"] for r in rec_a})}}
        rec_t = evaluate(by_time, rows)
        rep["time_forward"] = summarize(rec_t)
        rep["variance_decomposition"] = decompose(rows)
        d = rep["agency_out"]["all"]["M1-M0b"]
        rep["verdict_stage1"] = ("通过：要素在档内有可迁移的增益" if d["ci95"][1] < 0 and
                                 rep["agency_out"]["all"]["M1"]["rps"] <= rep["agency_out"]["all"]["M0"]["rps"]
                                 else "未通过：要素在未见机关上没有可确认的增益")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "report_dev.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return
    raise SystemExit("heldout 模式待工单 C 交回后按预注册补充（冻结模型、只跑一次）")


if __name__ == "__main__":
    main()

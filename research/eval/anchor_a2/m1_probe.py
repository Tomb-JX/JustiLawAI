"""M1 抽取探针：用 qwen3.5:9b 抽取 CAIL 赌博子集的要素，检验"高质量要素"能否超过纯文本基线。

结果按案例缓存到 $JUSTILAW_DATA_DIR/engine/m1_probe/<id>.json（分工文档 §3：引擎产物写 engine/），可中断续跑。

用法（仓库根目录）：
  research/.venv/Scripts/python.exe research/eval/anchor_a2/m1_probe.py run valid --limit 20 --workers 2
  research/.venv/Scripts/python.exe research/eval/anchor_a2/m1_probe.py report
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "justilaw-api"))
import a2_cail as A2  # noqa: E402
from app.discretion import extract as ex  # noqa: E402

OUT = A2.DATA_DIR / "engine" / "m1_probe"


def _one(case: dict) -> dict:
    path = OUT / f"{case['id']}.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    target = case["criminals"][0] if case["criminals"] else None
    try:
        r = ex.extract(case["fact"], target)
        rec = {"id": case["id"], "ok": True, "seconds": r.seconds, "eval_tokens": r.eval_tokens,
               "elements": r.elements.model_dump(mode="json"), "dropped": r.dropped, "raw": r.raw}
    except Exception as e:  # 单件失败不影响整批；记录后可重跑
        rec = {"id": case["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}
    if rec["ok"]:
        path.write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
    return rec


def cmd_run(split: str, limit: int | None, workers: int):
    OUT.mkdir(parents=True, exist_ok=True)
    cases, _ = A2.load_cases()
    ids = A2.read_split(split)[:limit] if limit else A2.read_split(split)
    t0 = time.time()
    done = fail = 0
    with ThreadPoolExecutor(workers) as pool:
        for rec in pool.map(_one, (cases[i] for i in ids)):
            done += rec["ok"]
            fail += not rec["ok"]
            if not rec["ok"]:
                print("失败", rec["id"], rec["error"])
    wall = time.time() - t0
    print(f"{split}：{len(ids)} 件，成功 {done}，失败 {fail}，墙钟 {wall:.0f} 秒，平均 {wall / max(len(ids), 1):.1f} 秒/件")


def cmd_report():
    recs = [json.loads(p.read_text("utf-8")) for p in OUT.glob("*.json")]
    if not recs:
        print("还没有结果")
        return
    secs = sorted(r["seconds"] for r in recs)
    toks = [r["eval_tokens"] for r in recs]
    print(f"已抽取 {len(recs)} 件；单件耗时 中位 {secs[len(secs) // 2]:.1f}s，p95 {secs[int(len(secs) * 0.95) - 1]:.1f}s；"
          f"平均输出 {sum(toks) / len(toks):.0f} tokens，约 {sum(toks) / sum(secs):.1f} tokens/s")
    filled = Counter()
    for r in recs:
        for group, fields in r["elements"].items():
            if isinstance(fields, dict):
                for name, v in fields.items():
                    if isinstance(v, dict) and v.get("value") is not None:
                        filled[f"{group}.{name}"] += 1
    print("字段抽取率（有值的案例占比）：")
    for path, n in filled.most_common():
        print(f"  {path:<40}{n / len(recs):>6.0%}")
    reasons = Counter(d["reason"] for r in recs for d in r["dropped"])
    n_items, truncated = 0, 0
    for r in recs:
        try:
            n_items += len(json.loads(r["raw"]).get("items", []))
        except json.JSONDecodeError:
            truncated += 1
    print(f"模型输出条目 {n_items} 条；输出被截断或不是合法 JSON 的案例 {truncated} 件；丢弃：" +
          ("，".join(f"{k} {v}" for k, v in reasons.items()) or "无"))


# ---------- 评估：抽取的要素能否超过纯文本 ----------

def _load_elements(cid: str):
    from app.discretion.schema import GamblingElements
    p = OUT / f"{cid}.json"
    if not p.exists():
        return None
    return GamblingElements.model_validate(json.loads(p.read_text("utf-8"))["elements"])


def element_vector(e, case: dict) -> list[float]:
    """要素 → 数值特征。缺失记 NaN：梯度提升树会为"缺失"单独学一个分支方向，而不是把它当成 0。"""
    import math
    from enum import Enum

    from app.discretion.schema import AmountRange, BehaviorType, GamblingMethod, Role, VenueType, iter_fields
    nan = float("nan")
    onehots = {"conduct.behavior_type": BehaviorType, "conduct.role": Role,
               "conduct.method": GamblingMethod, "venue.venue_type": VenueType}
    feats = []
    for path, _, typ in iter_fields():
        group, name = path.split(".")
        v = getattr(getattr(e, group), name).value
        if path in onehots:
            feats += [float(v == m) if v is not None else nan for m in onehots[path]]
        elif isinstance(v, AmountRange):
            # 开口（"万元以上"）只取下界，不按数量级补上界
            feats.append(math.log1p(v.min if v.max is None else (v.min + v.max) / 2))
        elif isinstance(v, bool):
            feats.append(float(v))
        elif isinstance(v, (int, float)):
            feats.append(math.log1p(max(v, 0)))
        elif v is None or isinstance(v, Enum):
            feats.append(nan)
        else:                       # 日期等：只记"是否有"
            feats.append(1.0)
    feats += [float(case["charge"] == "开设赌场"), math.log1p(len(case["fact"]))]
    return feats


def cmd_evaluate():
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import Pipeline

    import metrics as M  # noqa: E402

    cases, _ = A2.load_cases()
    tr_ids = [i for i in A2.read_split("train") if (OUT / f"{i}.json").exists()]
    va_ids = [i for i in A2.read_split("valid") if (OUT / f"{i}.json").exists()]
    tr, va = [cases[i] for i in tr_ids], [cases[i] for i in va_ids]
    y_tr, y_va = np.array([c["cls"] for c in tr]), np.array([c["cls"] for c in va])
    E_tr = np.array([element_vector(_load_elements(c["id"]), c) for c in tr])
    E_va = np.array([element_vector(_load_elements(c["id"]), c) for c in va])
    # 训练集中取值少于 2 种的列（例如整列都没抽到）没有信息，梯度提升树也无法分箱，去掉
    keep = [j for j in range(E_tr.shape[1]) if len(set(E_tr[~np.isnan(E_tr[:, j]), j])) >= 2]
    E_tr, E_va = E_tr[:, keep], E_va[:, keep]
    print(f"训练 {len(tr)} 件、验证 {len(va)} 件（均已抽取要素）；要素特征 {len(keep)} 列")

    text = Pipeline([("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                                               min_df=2, max_features=200_000)),
                     ("clf", LogisticRegression(C=3.0, max_iter=3000))])
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=A2.SEED)
    oof = np.zeros((len(tr), len(A2.PT_NAMES)))
    oof[:, sorted(set(y_tr))] = cross_val_predict(text, [c["fact"] for c in tr], y_tr, cv=cv, method="predict_proba")
    text.fit([c["fact"] for c in tr], y_tr)
    va_text = np.zeros((len(va), len(A2.PT_NAMES)))
    va_text[:, text.named_steps["clf"].classes_] = text.predict_proba([c["fact"] for c in va])
    text_pred = va_text.argmax(axis=1)

    gb = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0,
              early_stopping=True, validation_fraction=0.15, random_state=A2.SEED)
    rep = {k: float(np.median([c["months"] for c in tr if c["cls"] == k])) for k in set(y_tr)}
    m_va = [c["months"] for c in va]
    base_ok = (y_va == text_pred).astype(float)
    systems = {"T 文本（同训练集）": text_pred}
    for name, (Xa, Xb) in {"E 要素": (E_tr, E_va),
                           "E+T 要素+文本": (np.hstack([E_tr, oof]), np.hstack([E_va, va_text]))}.items():
        systems[name] = HistGradientBoostingClassifier(**gb).fit(Xa, y_tr).predict(Xb)
    for name, pred in systems.items():
        r = A2.evaluate(y_va, pred, m_va, [rep.get(p, 6.0) for p in pred])
        ok = (y_va == pred).astype(float)
        cmp = M.paired_bootstrap(lambda i: ok[i].mean(), lambda i: base_ok[i].mean(), len(va), n_resamples=5000)
        print(f"{name:<14} Acc {r['acc']:.2f} [{r['acc_ci'][0]:.1f}, {r['acc_ci'][1]:.1f}]  Ma-F {r['ma_f']:.2f}  "
              f"CAIL {r['cail_log']:.2f}  相对 T：{cmp['diff'] * 100:+.2f} [{cmp['ci_low'] * 100:+.2f}, {cmp['ci_high'] * 100:+.2f}]")


def cmd_diagnose():
    """在全部已抽取案例上做 5×5 折重复交叉验证，比较多种模型形式，判断要素是否真的不如文本。

    两类模型形式：
    - 分类：10 个区间当作互不相关的类别
    - 有序回归：预测 log(1+月数)，再按区间边界映射回类别（利用区间的大小顺序，方差更小）
    """
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.model_selection import KFold
    from sklearn.pipeline import Pipeline

    import metrics as M  # noqa: E402

    cases, _ = A2.load_cases()
    ids = [i for i in A2.read_split("train") + A2.read_split("valid") if (OUT / f"{i}.json").exists()]
    cs = [cases[i] for i in ids]
    y = np.array([c["cls"] for c in cs])
    logm = np.log1p([c["months"] for c in cs])
    texts = [c["fact"] for c in cs]
    E = np.array([element_vector(_load_elements(c["id"]), c) for c in cs])

    def tfidf():
        return TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True, min_df=2, max_features=200_000)

    def clean(Etr, Ete):
        keep = [j for j in range(Etr.shape[1]) if len(set(Etr[~np.isnan(Etr[:, j]), j])) >= 2]
        return Etr[:, keep], Ete[:, keep]

    def to_cls(pred_logm):
        return np.array([A2.pt_cls(m) for m in np.expm1(pred_logm)])

    reg_hgb = dict(max_iter=400, learning_rate=0.04, max_leaf_nodes=7, min_samples_leaf=40,
                   l2_regularization=1.0, early_stopping=True, validation_fraction=0.15, random_state=A2.SEED)

    def systems(tr, te):
        out = {}
        # 文本：分类 / 有序回归
        lr = Pipeline([("t", tfidf()), ("m", LogisticRegression(C=3.0, max_iter=3000))]).fit([texts[i] for i in tr], y[tr])
        out["T 分类(LR)"] = lr.predict([texts[i] for i in te])
        rg = Pipeline([("t", tfidf()), ("m", Ridge(alpha=1.0))]).fit([texts[i] for i in tr], logm[tr])
        t_reg_te = rg.predict([texts[i] for i in te])
        out["T 有序回归(Ridge)"] = to_cls(t_reg_te)
        # 要素：分类 / 有序回归（强正则的梯度提升树）
        Etr, Ete = clean(E[tr], E[te])
        out["E 分类(HGB)"] = HistGradientBoostingClassifier(**reg_hgb).fit(Etr, y[tr]).predict(Ete)
        out["E 有序回归(HGB)"] = to_cls(HistGradientBoostingRegressor(**reg_hgb).fit(Etr, logm[tr]).predict(Ete))
        # 要素 + 文本：文本回归的折外预测作为一个特征（在训练折内部再做 5 折，避免泄漏）
        oof = np.zeros(len(tr))
        for itr, ite in KFold(5, shuffle=True, random_state=A2.SEED).split(tr):
            m = Pipeline([("t", tfidf()), ("m", Ridge(alpha=1.0))]).fit([texts[tr[i]] for i in itr], logm[tr][itr])
            oof[ite] = m.predict([texts[tr[i]] for i in ite])
        Xtr, Xte = np.column_stack([Etr, oof]), np.column_stack([Ete, t_reg_te])
        out["E+T 有序回归(HGB)"] = to_cls(HistGradientBoostingRegressor(**reg_hgb).fit(Xtr, logm[tr]).predict(Xte))
        return out

    folds: dict[str, dict] = {}
    for fid, tr, te in A2.cv_folds(ids, list(y)):
        for name, pred in systems(tr, te).items():
            folds.setdefault(name, {})[fid] = {
                "acc": float((pred == y[te]).mean()),
                "cail": M.cail_log_score([cases[ids[i]]["months"] for i in te],
                                         [float(np.median([c["months"] for c in cs if c["cls"] == p] or [6])) for p in pred]),
                "n_train": len(tr), "n_test": len(te)}
        print(".", end="", flush=True)
    print(f"\n{len(ids)} 件，5×5 折")
    base = "T 分类(LR)"
    for name, fr in folds.items():
        accs = [f["acc"] for f in fr.values()]
        line = f"{name:<18} Acc {np.mean(accs) * 100:6.2f} ± {np.std(accs, ddof=1) * 100:4.2f}  CAIL {np.mean([f['cail'] for f in fr.values()]):6.2f}"
        if name != base:
            d = [fr[k]["acc"] - folds[base][k]["acc"] for k in fr]
            t = M.corrected_resampled_ttest(d, fr[next(iter(fr))]["n_train"], fr[next(iter(fr))]["n_test"])
            line += f"  相对 {base}：{t['mean_diff'] * 100:+.2f}（修正 t 检验 单侧 p = {t['p_value']:.3f}）"
        print(line)
    (HERE / "m1_diagnose.json").write_text(json.dumps(folds, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1]
    if cmd == "run":
        split = sys.argv[2]
        limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 1
        cmd_run(split, limit, workers)
    elif cmd == "report":
        cmd_report()
    elif cmd == "evaluate":
        cmd_evaluate()
    elif cmd == "diagnose":
        cmd_diagnose()

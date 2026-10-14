"""公开锚点 A2：CAIL2018 赌博子集上的刑期区间预测（门禁文档 §4 A2）。

协议（与 PLJP / MSR² 一致）：
- 数据：CAIL2018 exercise + final，单罪名单法条，去死刑、无期、零刑期（数据链路 fetch_cail.py 已过滤），
  只保留赌博罪、开设赌场罪
- 标签：PLJP 官方评测代码 mycode/metrics/evaluation_penalty.py 的 10 个刑期区间
- 指标：Acc = micro-F1；Ma-P / Ma-R / Ma-F 为 scikit-learn macro（标签取真值与预测的并集），附 CAIL 对数分

本文件额外做的：
- 事实文本完全相同的样本去重（CAIL 原始划分之间有重复，会造成训练–测试泄漏）
- 按固定种子重新 8:1:1 划分；只把样本 id 写入仓库，测试部分在门禁前不评测

用法（仓库根目录，研究环境）：
  research/.venv/Scripts/python.exe research/eval/anchor_a2/a2_cail.py prepare
  research/.venv/Scripts/python.exe research/eval/anchor_a2/a2_cail.py baselines
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import metrics as M  # noqa: E402

DATA_DIR = Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research"))
SRC = DATA_DIR / "cail" / "gambling"
SPLIT_DIR = HERE / "splits"
LEADERBOARD = HERE.parent / "leaderboard.csv"
SEED = 20261015

# PLJP evaluation_penalty.py 的区间定义（逐条照搬，月）
PT_NAMES = ["其他", "六个月以下", "六到九个月", "九个月到一年", "一到两年", "二到三年",
            "三到五年", "五到七年", "七到十年", "十年以上"]


def pt_cls(months: float) -> int:
    for k, lower in ((9, 120), (8, 84), (7, 60), (6, 36), (5, 24), (4, 12), (3, 9), (2, 6), (1, 0)):
        if months > lower:
            return k
    return 0


# ---------- 数据 ----------

def iter_json_objects(path: Path):
    """同时兼容标准 JSONL 与"记录首尾相连"的文件（数据链路已知 bug，见协作记录）。"""
    text = path.read_text("utf-8")
    dec, i, n = json.JSONDecoder(), 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        obj, i = dec.raw_decode(text, i)
        yield obj


def case_id(fact: str) -> str:
    return hashlib.sha1("".join(fact.split()).encode("utf-8")).hexdigest()[:16]


def load_cases() -> tuple[dict[str, dict], dict]:
    """返回 {id: case} 与统计。完全相同的事实只保留一份；同一事实标签冲突的整组丢弃。"""
    cases, labels, stats = {}, {}, Counter()
    for split in ("train", "valid", "test", "final_test"):
        for doc in iter_json_objects(SRC / f"{split}.jsonl"):
            stats["raw"] += 1
            meta = doc["meta"]
            cid = case_id(doc["fact"])
            label = (meta["accusation"][0], meta["term_of_imprisonment"]["imprisonment"])
            if cid in cases:
                stats["duplicate"] += 1
                if labels[cid] != label:
                    labels[cid] = None
                continue
            labels[cid] = label
            cases[cid] = {"id": cid, "fact": doc["fact"], "charge": label[0], "months": label[1],
                          "fine": meta.get("punish_of_money"), "cls": pt_cls(label[1]),
                          "criminals": meta.get("criminals") or []}
    conflict = [cid for cid, lab in labels.items() if lab is None]
    for cid in conflict:
        del cases[cid]
    stats["label_conflict_dropped"] = len(conflict)
    stats["kept"] = len(cases)
    # 只有公诉套话、几乎没有事实细节的样本（CAIL 已知噪声）：只统计，不删除，保持与公开协议可比
    stats["uninformative(<60字)"] = sum(len(c["fact"]) < 60 for c in cases.values())
    return cases, dict(stats)


def read_split(name: str) -> list[str]:
    return (SPLIT_DIR / f"{name}.ids").read_text("utf-8").split()


def cmd_prepare():
    cases, stats = load_cases()
    ids = sorted(cases)
    random.Random(SEED).shuffle(ids)
    n = len(ids)
    parts = {"train": ids[: int(n * 0.8)], "valid": ids[int(n * 0.8): int(n * 0.9)], "test": ids[int(n * 0.9):]}
    SPLIT_DIR.mkdir(exist_ok=True)
    for name, part in parts.items():
        (SPLIT_DIR / f"{name}.ids").write_text("\n".join(part) + "\n", "utf-8")
    lines = ["# A2 数据统计（自动生成）", "", f"- 种子：{SEED}；划分 8:1:1（按去重后的事实随机划分）"]
    lines += [f"- {k}：{v}" for k, v in stats.items()]
    for name, part in parts.items():
        dist = Counter(cases[i]["cls"] for i in part)
        lines.append(f"- {name}：{len(part)} 件；区间分布 " +
                     "，".join(f"{PT_NAMES[k]} {dist[k]}" for k in sorted(dist)))
    charge = Counter(c["charge"] for c in cases.values())
    lines.append("- 罪名：" + "，".join(f"{k} {v}" for k, v in charge.most_common()))
    (SPLIT_DIR / "stats.md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))


# ---------- 基线 ----------

def evaluate(y_true, y_pred, months_true, months_pred, proba=None) -> dict:
    from sklearn.metrics import precision_recall_fscore_support
    acc = float(np.mean(np.asarray(y_true) == np.asarray(y_pred)))
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    out = {"acc": acc * 100, "ma_p": p * 100, "ma_r": r * 100, "ma_f": f * 100,
           "cail_log": M.cail_log_score(months_true, months_pred)}
    if proba is not None:
        idx = {c: i for i, c in enumerate(range(len(PT_NAMES)))}
        out["rps"] = M.rps(proba, [idx[y] for y in y_true])
        out["ece"] = M.ece(proba, [idx[y] for y in y_true])
    # 准确率的 95% 自助法置信区间
    correct = (np.asarray(y_true) == np.asarray(y_pred)).astype(float)
    rng = np.random.default_rng(0)
    boots = [correct[rng.integers(0, len(correct), len(correct))].mean() for _ in range(2000)]
    out["acc_ci"] = tuple(float(x) * 100 for x in np.quantile(boots, [0.025, 0.975]))
    return out


def cmd_baselines():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV, StratifiedKFold
    from sklearn.pipeline import Pipeline
    from sklearn.svm import LinearSVC

    cases, _ = load_cases()
    tr = [cases[i] for i in read_split("train")]
    va = [cases[i] for i in read_split("valid")]
    X_tr, y_tr = [c["fact"] for c in tr], np.array([c["cls"] for c in tr])
    X_va, y_va = [c["fact"] for c in va], np.array([c["cls"] for c in va])
    m_va = [c["months"] for c in va]
    # 区间 → 代表月数：训练集中该区间的中位数（用于 CAIL 对数分）
    rep = {k: float(np.median([c["months"] for c in tr if c["cls"] == k])) for k in set(y_tr)}

    results = {}
    maj = Counter(y_tr).most_common(1)[0][0]
    results["B-majority"] = (evaluate(y_va, [maj] * len(y_va), m_va, [rep[maj]] * len(y_va)),
                             f"恒预测训练集最多的区间（{PT_NAMES[maj]}）")

    tfidf = dict(analyzer="char", ngram_range=(1, 3), sublinear_tf=True, min_df=2, max_features=200_000)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    searches = {
        "B4-tfidf-svm": (Pipeline([("tfidf", TfidfVectorizer(**tfidf)), ("clf", LinearSVC())]),
                         {"clf__C": [0.1, 0.3, 1.0, 3.0], "clf__class_weight": [None, "balanced"]}),
        "B4-tfidf-lr": (Pipeline([("tfidf", TfidfVectorizer(**tfidf)), ("clf", LogisticRegression(max_iter=3000))]),
                        {"clf__C": [1.0, 3.0, 10.0, 30.0], "clf__class_weight": [None, "balanced"]}),
    }
    for name, (pipe, grid) in searches.items():
        gs = GridSearchCV(pipe, grid, cv=cv, scoring="accuracy", n_jobs=-1).fit(X_tr, y_tr)
        pred = gs.predict(X_va)
        proba = None
        if name.endswith("lr"):
            # 训练集里没出现过的区间概率记 0，概率矩阵统一为 10 列
            proba = np.zeros((len(X_va), len(PT_NAMES)))
            proba[:, gs.best_estimator_.named_steps["clf"].classes_] = gs.predict_proba(X_va)
        results[name] = (evaluate(y_va, pred, m_va, [rep[p] for p in pred], proba),
                         f"字符 1–3 元 TF-IDF；5 折交叉验证选参 {gs.best_params_}，交叉验证准确率 {gs.best_score_*100:.2f}")

    rows = []
    print(f"验证集 {len(va)} 件（测试集封存，未评测）")
    print(f"{'系统':<16}{'Acc':>8}{'Acc 95%CI':>18}{'Ma-P':>8}{'Ma-R':>8}{'Ma-F':>8}{'CAIL':>8}{'RPS':>8}{'ECE':>8}")
    for name, (r, desc) in results.items():
        ci = f"[{r['acc_ci'][0]:.1f}, {r['acc_ci'][1]:.1f}]"
        print(f"{name:<16}{r['acc']:>8.2f}{ci:>18}{r['ma_p']:>8.2f}{r['ma_r']:>8.2f}{r['ma_f']:>8.2f}"
              f"{r['cail_log']:>8.2f}{r.get('rps', float('nan')):>8.4f}{r.get('ece', float('nan')):>8.4f}")
        print(f"  {desc}")
        for metric in ("acc", "ma_p", "ma_r", "ma_f", "cail_log", "rps", "ece"):
            if metric in r:
                lo, hi = r["acc_ci"] if metric == "acc" else ("", "")
                rows.append([date.today().isoformat(), "A2-dev", name, desc, "cail-gambling-valid",
                             "", "", "", hashlib.sha1("".join(read_split("valid")).encode()).hexdigest()[:12],
                             SEED, metric, round(r[metric], 4), lo, hi, "no"])
    with LEADERBOARD.open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)


# ---------- 门禁 A2 判定框架：5 × 5 折重复分层交叉验证（门禁文档 §4 A2 v0.3） ----------

CV_SEEDS = (11, 22, 33, 44, 55)
CV_RESULTS = HERE / "cv_results.json"


def cv_folds(ids: list[str], labels: list[int]):
    """固定的 25 个划分（5 个种子 × 5 折）。任何系统都在完全相同的划分上评估，才能逐折配对。"""
    from sklearn.model_selection import StratifiedKFold
    for seed in CV_SEEDS:
        for k, (tr, te) in enumerate(StratifiedKFold(5, shuffle=True, random_state=seed).split(ids, labels)):
            yield f"s{seed}-f{k}", tr, te


def text_system(kind: str):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.svm import LinearSVC
    clf = LinearSVC(C=0.3) if kind == "svm" else LogisticRegression(C=3.0, max_iter=3000)
    return Pipeline([("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                                               min_df=2, max_features=200_000)), ("clf", clf)])


def cmd_cv():
    from sklearn.metrics import f1_score
    cases, _ = load_cases()
    pool = read_split("train") + read_split("valid")          # 封存的测试部分不参与
    y = np.array([cases[i]["cls"] for i in pool])
    X = [cases[i]["fact"] for i in pool]
    results = json.loads(CV_RESULTS.read_text("utf-8")) if CV_RESULTS.exists() else {}
    for name in ("B-majority", "B4-tfidf-svm", "B4-tfidf-lr"):
        if name in results:
            continue
        folds = {}
        for fid, tr, te in cv_folds(pool, list(y)):
            if name == "B-majority":
                pred = np.full(len(te), Counter(y[tr]).most_common(1)[0][0])
            else:
                model = text_system("svm" if "svm" in name else "lr").fit([X[i] for i in tr], y[tr])
                pred = model.predict([X[i] for i in te])
            folds[fid] = {"acc": float((pred == y[te]).mean()),
                          "ma_f": float(f1_score(y[te], pred, average="macro", zero_division=0)),
                          "n_train": len(tr), "n_test": len(te)}
        results[name] = folds
        CV_RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
        accs = [f["acc"] for f in folds.values()]
        mafs = [f["ma_f"] for f in folds.values()]
        print(f"{name:<14} 25 折 Acc {np.mean(accs) * 100:.2f} ± {np.std(accs, ddof=1) * 100:.2f}   "
              f"Ma-F {np.mean(mafs) * 100:.2f} ± {np.std(mafs, ddof=1) * 100:.2f}")


def compare_cv(system: str, baseline: str, metric: str = "acc") -> dict:
    """逐折配对 + 修正 t 检验（Nadeau & Bengio 2003）。"""
    res = json.loads(CV_RESULTS.read_text("utf-8"))
    a, b = res[system], res[baseline]
    diffs = [a[f][metric] - b[f][metric] for f in a]
    f0 = next(iter(a.values()))
    return M.corrected_resampled_ttest(diffs, f0["n_train"], f0["n_test"])


# ---------- 探针：结构化要素是否有增益（正则粗抽，仅用于诊断，不进入产品） ----------

_NUM = r"(\d+(?:\.\d+)?)\s*(万)?\s*余?\s*元"
PATTERNS = {
    "profit": re.compile(r"(?:抽头|抽水|渔利|获利|非法所得|违法所得|营利|台费|头钱)[^。；]{0,15}?" + _NUM),
    "stake": re.compile(r"赌资[^。；]{0,15}?" + _NUM),
}
FLAGS = {"累犯": "累犯", "前科": "前科|曾因", "自首": "自首|主动投案", "坦白": "如实供述|坦白",
         "退赃": "退出|退缴|退赃|退还", "网络": "网络|网站|微信|QQ|APP|app|平台", "赌博机": "赌博机|老虎机|捕鱼",
         "缓刑": "缓刑", "认罪认罚": "认罪认罚"}


def _amounts(pattern, text):
    return [float(m.group(1)) * (10000 if m.group(2) else 1) for m in pattern.finditer(text)]


def element_features(fact: str, charge: str) -> list[float]:
    feats = []
    for p in PATTERNS.values():
        vals = _amounts(p, fact)
        feats += [math.log1p(max(vals)) if vals else 0.0, float(bool(vals))]
    people = [int(x) for x in re.findall(r"(\d+)\s*(?:名|人)", fact) if int(x) < 1000]
    machines = [int(x) for x in re.findall(r"(\d+)\s*台", fact) if int(x) < 1000]
    feats += [max(people, default=0), max(machines, default=0)]
    feats += [float(bool(re.search(v, fact))) for v in FLAGS.values()]
    feats += [float(charge == "开设赌场"), math.log1p(len(fact))]
    return feats


def cmd_probe():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import Pipeline

    cases, _ = load_cases()
    tr = [cases[i] for i in read_split("train")]
    va = [cases[i] for i in read_split("valid")]
    y_tr, y_va = np.array([c["cls"] for c in tr]), np.array([c["cls"] for c in va])
    F_tr = np.array([element_features(c["fact"], c["charge"]) for c in tr])
    F_va = np.array([element_features(c["fact"], c["charge"]) for c in va])
    cover = {k: np.mean([bool(_amounts(p, c["fact"])) for c in tr]) for k, p in PATTERNS.items()}
    print("正则命中率（训练集）：" + "，".join(f"{k} {v:.0%}" for k, v in cover.items()))

    text = Pipeline([("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                                               min_df=2, max_features=200_000)),
                     ("clf", LogisticRegression(C=3.0, max_iter=3000))])
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    # 堆叠：文本模型在训练集上的"折外"概率作为特征，避免把训练集上过拟合的概率喂给第二层
    oof = cross_val_predict(text, [c["fact"] for c in tr], y_tr, cv=cv, method="predict_proba")
    text.fit([c["fact"] for c in tr], y_tr)
    va_text = text.predict_proba([c["fact"] for c in va])

    gb = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0,
              early_stopping=True, validation_fraction=0.15, random_state=SEED)
    models = {
        "P-elements": (F_tr, F_va),
        "P-elements+text": (np.hstack([F_tr, oof]), np.hstack([F_va, va_text])),
    }
    rep = {k: float(np.median([c["months"] for c in tr if c["cls"] == k])) for k in set(y_tr)}
    a = (np.asarray(y_va) == text.predict([c["fact"] for c in va])).astype(float)
    for name, (Xa, Xb) in models.items():
        clf = HistGradientBoostingClassifier(**gb).fit(Xa, y_tr)
        pred = clf.predict(Xb)
        r = evaluate(y_va, pred, [c["months"] for c in va], [rep[p] for p in pred])
        b = (np.asarray(y_va) == pred).astype(float)
        res = M.paired_bootstrap(lambda i: b[i].mean(), lambda i: a[i].mean(), len(va), n_resamples=5000)
        print(f"{name:<18} Acc {r['acc']:.2f} [{r['acc_ci'][0]:.1f}, {r['acc_ci'][1]:.1f}]  Ma-F {r['ma_f']:.2f}  "
              f"CAIL {r['cail_log']:.2f}  相对文本LR：差 {res['diff']*100:+.2f}，95%CI [{res['ci_low']*100:+.2f}, {res['ci_high']*100:+.2f}]")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    {"prepare": cmd_prepare, "baselines": cmd_baselines, "probe": cmd_probe, "cv": cmd_cv}[sys.argv[1]]()

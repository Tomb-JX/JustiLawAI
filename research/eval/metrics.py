"""评测指标（门禁文档 §3 的唯一实现）。

所有门禁、冻结基线、回归检查都只调用这里的函数；公式改动等同于改门禁，须登记偏离日志。
只依赖 numpy，参考实现（scikit-learn、pytrec_eval、CAIL 官方公式）的一致性由 tests/test_metrics.py 保证。
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Hashable, Sequence
from difflib import SequenceMatcher

import numpy as np

# ---------- M1 抽取 ----------


def value_correct(pred, gold, rel_tol: float = 0.05) -> bool:
    """字段级正确性（§3.1）。区间值 (min, max)：两区间重叠且端点相对误差都不超过 rel_tol；其余要求完全相等。"""
    if pred is None or gold is None:
        return pred is None and gold is None
    if isinstance(gold, (tuple, list)) and len(gold) == 2 and isinstance(pred, (tuple, list)):
        (p0, p1), (g0, g1) = pred, gold
        overlap = p0 <= g1 and g0 <= p1
        close = all(abs(p - g) <= rel_tol * max(abs(g), 1e-9) for p, g in ((p0, g0), (p1, g1)))
        return overlap and close
    return pred == gold


def field_accuracy(preds: Sequence, golds: Sequence, rel_tol: float = 0.05) -> float:
    return float(np.mean([value_correct(p, g, rel_tol) for p, g in zip(preds, golds, strict=True)]))


def field_micro_f1(preds: Sequence, golds: Sequence, rel_tol: float = 0.05) -> float:
    """非空值视为一次预测；"未提及"（None）为负类。"""
    tp = sum(1 for p, g in zip(preds, golds, strict=True) if p is not None and g is not None and value_correct(p, g, rel_tol))
    n_pred = sum(p is not None for p in preds)
    n_gold = sum(g is not None for g in golds)
    if n_pred == 0 and n_gold == 0:
        return 1.0
    prec = tp / n_pred if n_pred else 0.0
    rec = tp / n_gold if n_gold else 0.0
    return 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def evidence_found(quote: str, source: str, min_ratio: float = 0.9) -> bool:
    """证据引文能否在原文中找到：空白规范化后逐字包含，或与某个等长片段的字符相似度 ≥ min_ratio。"""
    q, s = _norm_ws(quote), _norm_ws(source)
    if not q:
        return False
    if q in s:
        return True
    n = len(q)
    best = 0.0
    for i in range(0, max(1, len(s) - n + 1)):
        best = max(best, SequenceMatcher(None, q, s[i:i + n], autojunk=False).ratio())
        if best >= min_ratio:
            return True
    return False


def evidence_hit_rate(quotes: Sequence[str], sources: Sequence[str], min_ratio: float = 0.9) -> float:
    return float(np.mean([evidence_found(q, s, min_ratio) for q, s in zip(quotes, sources, strict=True)]))


def unsupported_value_rate(preds: Sequence, golds: Sequence, evidence_ok: Sequence[bool]) -> float:
    """金标"未提及"、模型却给出非空值且证据不成立的比例（事实幻觉率），分母为全部字段。"""
    bad = sum(1 for p, g, ok in zip(preds, golds, evidence_ok, strict=True) if g is None and p is not None and not ok)
    return bad / len(preds) if len(preds) else 0.0


def auroc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """二分类 AUROC（Mann–Whitney，并列取平均秩）。"""
    s, y = np.asarray(scores, float), np.asarray(labels, int)
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


# ---------- M2–M4 分类与裁量 ----------


def macro_f1(y_true: Sequence[Hashable], y_pred: Sequence[Hashable], labels: Sequence[Hashable] | None = None) -> float:
    labels = list(labels) if labels is not None else sorted(set(y_true) | set(y_pred), key=str)
    f1s = []
    for c in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p != c)
        f1s.append(0.0 if 2 * tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s))


def recall_precision(y_true, y_pred, positive) -> tuple[float, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == positive and p == positive)
    n_true = sum(t == positive for t in y_true)
    n_pred = sum(p == positive for p in y_pred)
    return (tp / n_true if n_true else float("nan"), tp / n_pred if n_pred else float("nan"))


def mae(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    return float(np.mean(np.abs(np.asarray(y_true, float) - np.asarray(y_pred, float))))


def acc_within(y_true: Sequence[float], y_pred: Sequence[float], k: float) -> float:
    return float(np.mean(np.abs(np.asarray(y_true, float) - np.asarray(y_pred, float)) <= k))


def cail_log_score(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    """CAIL2018 官方刑期评分：d = |log(t+1) − log(t̂+1)|，按 0.2 步长分档得 1.0/0.8/0.6/0.4/0.2/0，平均 × 100。"""
    d = np.abs(np.log(np.asarray(y_true, float) + 1) - np.log(np.asarray(y_pred, float) + 1))
    score = np.select([d <= 0.2, d <= 0.4, d <= 0.6, d <= 0.8, d <= 1.0], [1.0, 0.8, 0.6, 0.4, 0.2], 0.0)
    return float(score.mean() * 100)


def relative_hit(y_true: Sequence[float], y_pred: Sequence[float], tol: float = 0.2) -> float:
    """罚款 ±20% 命中率：|ŷ − y| ≤ tol·y（y=0 时要求 ŷ=0）。"""
    t, p = np.asarray(y_true, float), np.asarray(y_pred, float)
    ok = np.where(t == 0, p == 0, np.abs(p - t) <= tol * np.abs(t))
    return float(ok.mean())


def rps(probs: np.ndarray, y_index: Sequence[int]) -> float:
    """排序概率评分（有序类别；越低越好），按 K−1 归一化到 [0, 1]。"""
    p = np.asarray(probs, float)
    k = p.shape[1]
    onehot = np.zeros_like(p)
    onehot[np.arange(len(p)), np.asarray(y_index)] = 1
    cp, co = np.cumsum(p, axis=1)[:, :-1], np.cumsum(onehot, axis=1)[:, :-1]
    return float((((cp - co) ** 2).sum(axis=1) / (k - 1)).mean())


def ece(probs: np.ndarray, y_index: Sequence[int], n_bins: int = 15) -> float:
    """期望校准误差（Guo et al. 2017）：按最大类概率等宽分 15 箱。"""
    p = np.asarray(probs, float)
    conf, pred = p.max(axis=1), p.argmax(axis=1)
    correct = (pred == np.asarray(y_index)).astype(float)
    edges = np.linspace(0, 1, n_bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


# ---------- 预测集（共形） ----------


def coverage(sets: Sequence[Callable[[float], bool] | set], y: Sequence) -> float:
    """sets 的元素可以是集合，也可以是判断"是否落在预测集内"的函数（预测集为若干区段的并集时用）。"""
    hits = [(s(v) if callable(s) else v in s) for s, v in zip(sets, y, strict=True)]
    return float(np.mean(hits))


def group_coverage(sets, y, groups: Sequence[Hashable], min_n: int = 50) -> dict:
    """分组覆盖率；n < min_n 的组只报告不判定（§6）。"""
    out = {}
    for g in dict.fromkeys(groups):
        idx = [i for i, gg in enumerate(groups) if gg == g]
        out[g] = {"n": len(idx), "coverage": coverage([sets[i] for i in idx], [y[i] for i in idx]),
                  "judged": len(idx) >= min_n}
    return out


def coverage_tolerance(n: int, alpha: float = 0.1) -> float:
    """§6：|ĉ − (1−α)| 允许的偏差 = max(0.02, 2·√(α(1−α)/n))。"""
    return max(0.02, 2 * math.sqrt(alpha * (1 - alpha) / n))


def mean_set_size(sizes: Sequence[float]) -> float:
    return float(np.mean(sizes))


# ---------- M5 检索（TREC 约定，与 pytrec_eval 一致） ----------


def _ranked(run: dict[str, float]) -> list[str]:
    # trec_eval 的排序：分数降序，分数相同时按文档 id 降序
    return [d for d, _ in sorted(run.items(), key=lambda x: (x[1], x[0]), reverse=True)]


def ndcg_at_k(qrels: dict[str, int], run: dict[str, float], k: int) -> float:
    """线性增益（trec_eval 默认），理想排序取 qrels 中全部已标注文档。"""
    ranked = _ranked(run)[:k]
    dcg = sum(qrels.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ranked))
    ideal = sorted((r for r in qrels.values() if r > 0), reverse=True)[:k]
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def average_precision(qrels: dict[str, int], run: dict[str, float], relevance_level: int = 1) -> float:
    rel = {d for d, r in qrels.items() if r >= relevance_level}
    if not rel:
        return 0.0
    hits, total = 0, 0.0
    for i, d in enumerate(_ranked(run)):
        if d in rel:
            hits += 1
            total += hits / (i + 1)
    return total / len(rel)


def precision_at_k(qrels: dict[str, int], run: dict[str, float], k: int, relevance_level: int = 1) -> float:
    ranked = _ranked(run)[:k]
    return sum(1 for d in ranked if qrels.get(d, 0) >= relevance_level) / k


# ---------- 鲁棒性 ----------


def tvd(p: Sequence[float], q: Sequence[float]) -> float:
    """总变差距离（不变性测试）。"""
    return float(0.5 * np.abs(np.asarray(p, float) - np.asarray(q, float)).sum())


# ---------- 统计判定（§6） ----------


def paired_bootstrap(metric: Callable[[Sequence[int]], float], baseline: Callable[[Sequence[int]], float],
                     n_items: int, groups: Sequence[Hashable] | None = None,
                     n_resamples: int = 10_000, seed: int = 0, alpha: float = 0.05) -> dict:
    """配对自助法（Koehn 2004）：按事件分组整体重采样。

    metric / baseline 接收一组样本下标，返回该子集上的指标值。
    返回差值（metric − baseline）的点估计、95% 置信区间与单侧 p 值（差值 ≤ 0 的比例）。
    """
    rng = np.random.default_rng(seed)
    groups = list(groups) if groups is not None else list(range(n_items))
    members: dict[Hashable, list[int]] = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(i)
    keys = list(members)
    all_idx = list(range(n_items))
    point = metric(all_idx) - baseline(all_idx)
    diffs = np.empty(n_resamples)
    for b in range(n_resamples):
        pick = rng.integers(0, len(keys), len(keys))
        idx = [i for k in pick for i in members[keys[k]]]
        diffs[b] = metric(idx) - baseline(idx)
    lo, hi = np.quantile(diffs, [alpha / 2, 1 - alpha / 2])
    return {"diff": float(point), "ci_low": float(lo), "ci_high": float(hi), "p_value": float((diffs <= 0).mean())}


def superior(result: dict, min_delta: float) -> bool:
    """"显著优于"：置信区间下限 > 0 且点估计差值 ≥ 规定增量。"""
    return result["ci_low"] > 0 and result["diff"] >= min_delta


def non_inferior(result: dict, delta: float) -> bool:
    """"不劣于"：差值置信区间下限 > −δ。"""
    return result["ci_low"] > -delta


def holm(p_values: Sequence[float], alpha: float = 0.05) -> list[bool]:
    """Holm 逐步校正：返回每个假设是否被拒绝（即对应的"优于"成立）。"""
    order = np.argsort(p_values)
    reject = [False] * len(p_values)
    for rank, i in enumerate(order):
        if p_values[i] <= alpha / (len(p_values) - rank):
            reject[i] = True
        else:
            break
    return reject

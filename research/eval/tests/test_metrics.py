"""指标实现与参考实现的一致性（门禁 G0.4：误差 ≤ 1e-6）。

运行：research/.venv/Scripts/python -m pytest research/eval/tests -q
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metrics as m  # noqa: E402

pytrec_eval = pytest.importorskip("pytrec_eval")
skm = pytest.importorskip("sklearn.metrics")
TOL = 1e-6


# ---------- CAIL 官方刑期评分（公式取自 CAIL2018 Overview 式 7–9） ----------

@pytest.mark.parametrize("true,pred,score", [
    (12, 12, 1.0),                 # d = 0
    (12, 14, 1.0),                 # d = log(15/13) ≈ 0.143
    (12, 16, 0.8),                 # d = log(17/13) ≈ 0.268
    (12, 20, 0.6),                 # d = log(21/13) ≈ 0.480
    (12, 26, 0.4),                 # d = log(27/13) ≈ 0.731
    (12, 30, 0.2),                 # d = log(31/13) ≈ 0.869
    (12, 40, 0.0),                 # d = log(41/13) ≈ 1.149
])
def test_cail_log_score_bands(true, pred, score):
    assert abs(m.cail_log_score([true], [pred]) - score * 100) < TOL


def test_cail_band_boundaries_inclusive():
    # d 恰好等于 0.2 时得 1.0（官方公式为 v ≤ 0.2）
    t = 10
    p = math.exp(0.2) * (t + 1) - 1
    assert abs(m.cail_log_score([t], [p - 1e-9]) - 100) < TOL


# ---------- 分类指标 vs scikit-learn ----------

def test_macro_f1_matches_sklearn():
    rng = np.random.default_rng(1)
    y, p = rng.integers(0, 4, 300), rng.integers(0, 4, 300)
    ref = skm.f1_score(y, p, average="macro", labels=[0, 1, 2, 3])
    assert abs(m.macro_f1(list(y), list(p), labels=[0, 1, 2, 3]) - ref) < TOL


def test_auroc_matches_sklearn_with_ties():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 2, 500)
    s = np.round(rng.random(500) + 0.3 * y, 1)          # 大量并列
    assert abs(m.auroc(s, y) - skm.roc_auc_score(y, s)) < TOL


def test_mae_matches_sklearn():
    rng = np.random.default_rng(3)
    t, p = rng.integers(0, 16, 200), rng.integers(0, 16, 200)
    assert abs(m.mae(t, p) - skm.mean_absolute_error(t, p)) < TOL


# ---------- 检索指标 vs pytrec_eval ----------

def _random_trec(seed):
    rng = np.random.default_rng(seed)
    qrels, run = {}, {}
    for q in range(20):
        docs = [f"d{q}_{i}" for i in range(40)]
        qrels[f"q{q}"] = {d: int(rng.integers(0, 4)) for d in docs[:30]}
        run[f"q{q}"] = {d: float(np.round(rng.random(), 2)) for d in docs}   # 含并列分数与未标注文档
    return qrels, run


def test_retrieval_metrics_match_pytrec_eval():
    qrels, run = _random_trec(4)
    ev = pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut.10", "ndcg_cut.3", "map", "P.3"}, relevance_level=2)
    ref = ev.evaluate(run)
    for q in qrels:
        assert abs(m.ndcg_at_k(qrels[q], run[q], 10) - ref[q]["ndcg_cut_10"]) < TOL
        assert abs(m.ndcg_at_k(qrels[q], run[q], 3) - ref[q]["ndcg_cut_3"]) < TOL
        assert abs(m.average_precision(qrels[q], run[q], relevance_level=2) - ref[q]["map"]) < TOL
        assert abs(m.precision_at_k(qrels[q], run[q], 3, relevance_level=2) - ref[q]["P_3"]) < TOL


# ---------- 其他指标 ----------

def test_rps_perfect_and_worst():
    assert m.rps(np.array([[0, 1, 0]]), [1]) == 0
    assert abs(m.rps(np.array([[1, 0, 0]]), [2]) - 1) < TOL


def test_ece_perfectly_calibrated_is_zero():
    probs = np.array([[0.8, 0.2]] * 10)
    y = [0] * 8 + [1] * 2
    assert abs(m.ece(probs, y)) < TOL


def test_coverage_tolerance_rule():
    assert m.coverage_tolerance(10_000) == 0.02
    assert abs(m.coverage_tolerance(150) - 2 * math.sqrt(0.09 / 150)) < TOL


def test_coverage_with_interval_union():
    sets = [lambda d: d == 5 or 10 <= d <= 12, {0}]
    assert m.coverage(sets, [11, 0]) == 1.0
    assert m.coverage(sets, [7, 0]) == 0.5


def test_value_correct_ranges():
    assert m.value_correct((3000, 3999), (3000, 3999))
    assert m.value_correct((3000, 3999), (3050, 3999))       # 端点误差 < 5%
    assert not m.value_correct((3000, 3999), (5000, 6000))
    assert m.value_correct(None, None) and not m.value_correct(None, 3)


def test_evidence_found():
    src = "民警现场查获赌资合计4600元。"
    assert m.evidence_found("查获赌资合计4600元", src)
    assert m.evidence_found("查获赌资 合计4600元", src)        # 空白差异
    assert not m.evidence_found("查获赌资合计9900元，另有手机三部", src)


def test_holm():
    assert m.holm([0.01, 0.04, 0.03]) == [True, False, False]
    assert m.holm([0.001, 0.01, 0.02]) == [True, True, True]


def test_paired_bootstrap_detects_real_difference():
    rng = np.random.default_rng(5)
    a = rng.random(400) < 0.8          # 系统 A 正确率约 0.8
    b = rng.random(400) < 0.6          # 系统 B 约 0.6
    res = m.paired_bootstrap(lambda i: a[i].mean(), lambda i: b[i].mean(), 400, n_resamples=2000)
    assert m.superior(res, 0.1)
    same = m.paired_bootstrap(lambda i: a[i].mean(), lambda i: a[i].mean(), 400, n_resamples=500)
    assert same["diff"] == 0 and not m.superior(same, 0.0)


def test_tvd():
    assert m.tvd([0.5, 0.5], [0.5, 0.5]) == 0
    assert abs(m.tvd([1, 0], [0, 1]) - 1) < TOL

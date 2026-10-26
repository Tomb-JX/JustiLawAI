"""E-03：固定首跑 B4 的逐类、文本稀疏度与罚款误差诊断。"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.pipeline import make_pipeline

from dev_slice_first_run import DEFAULT_SLICE, _vectorizer, load_slice, text_input


def _quartiles(values: list[float], correct: list[bool]) -> list[dict]:
    order = np.argsort(np.asarray(values), kind="stable")
    groups = np.array_split(order, 4)
    return [{"n": len(idx), "min": float(min(values[i] for i in idx)),
             "max": float(max(values[i] for i in idx)),
             "accuracy": float(np.mean([correct[i] for i in idx]))} for idx in groups]


def diagnose(rows: list[dict]) -> dict:
    train = [r for r in rows if r["development_split"] == "train"]
    val = [r for r in rows if r["development_split"] == "validation"]
    Xtr, Xva = [text_input(r) for r in train], [text_input(r) for r in val]
    ytr, yva = [r["observed_outcome"]["type"] for r in train], [r["observed_outcome"]["type"] for r in val]
    clf = make_pipeline(_vectorizer(), LogisticRegression(C=3.0, max_iter=3000)).fit(Xtr, ytr)
    pred = clf.predict(Xva)
    labels = sorted(set(ytr) | set(yva))
    correct = [a == b for a, b in zip(yva, pred, strict=True)]
    matrix = confusion_matrix(yva, pred, labels=labels).tolist()
    per_class = classification_report(yva, pred, labels=labels, output_dict=True, zero_division=0)
    tfidf: TfidfVectorizer = clf.named_steps["tfidfvectorizer"]
    nnz = np.asarray(tfidf.transform(Xva).getnnz(axis=1)).tolist()
    lengths = [len(x) for x in Xva]
    fine_train = np.asarray([r["observed_outcome"]["fine"] for r in train], float)
    fine_val = np.asarray([r["observed_outcome"]["fine"] for r in val], float)
    ridge = make_pipeline(_vectorizer(), Ridge(alpha=1.0)).fit(Xtr, np.log1p(fine_train))
    fine_pred = np.expm1(ridge.predict(Xva)).clip(min=0)
    fine_median = np.expm1(np.median(np.log1p(fine_train)))
    by_fine_presence = {}
    for name, mask in (("zero", fine_val == 0), ("positive", fine_val > 0)):
        if mask.any():
            by_fine_presence[name] = {"n": int(mask.sum()),
                                      "median_mae": float(np.mean(abs(fine_val[mask] - fine_median))),
                                      "B4_mae": float(np.mean(abs(fine_val[mask] - fine_pred[mask]))),
                                      "B4_pred_median": float(np.median(fine_pred[mask]))}
    errors = [{"id": r["id"], "observed": true, "predicted": str(guess),
               "input_length": lengths[i], "known_ngrams": nnz[i]}
              for i, (r, true, guess) in enumerate(zip(val, yva, pred, strict=True)) if true != guess]
    return {"train_n": len(train), "validation_n": len(val), "train_distribution": dict(Counter(ytr)),
            "validation_distribution": dict(Counter(yva)),
            "label_order": labels, "confusion_rows_true_cols_pred": matrix,
            "per_class": {label: per_class[label] for label in labels},
            "prediction_distribution": dict(Counter(str(x) for x in pred)),
            "input_length_quartiles": _quartiles(lengths, correct),
            "known_ngram_quartiles": _quartiles(nnz, correct),
            "fine_presence_error": by_fine_presence, "wrong_n": len(errors),
            "wrong_ids": [x["id"] for x in errors], "error_examples": errors[:12],
            "pre_registered_next_baseline": {
                "model": "同一字符 TF-IDF + LogisticRegression(C=3.0, class_weight='balanced')",
                "fit": "只在开发 train 训练；固定参数，不在 validation/test 搜参",
                "compare": "同一 validation 的准确率、Macro-F1、逐类召回；事件级配对差异",
                "status": "proposed_not_run"}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, default=DEFAULT_SLICE)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows, _, hashes = load_slice(args.slice)
    report = {"task": "E-03", "manifest_sha256": hashes["manifest.json"],
              "development_only": True, "test_evaluated": False, "diagnosis": diagnose(rows)}
    out = args.out or args.slice.parents[1] / "engine" / "development" / f"{args.slice.name}-m4-diagnosis.json"
    if out.exists():
        raise FileExistsError("诊断报告不可覆盖；指定新 --out")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    d = report["diagnosis"]
    print(json.dumps({"out": str(out), "wrong_n": d["wrong_n"],
                      "confusion": d["confusion_rows_true_cols_pred"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

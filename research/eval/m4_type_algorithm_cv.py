"""Fixed-fold comparison of flat and factorized M4 type prediction.

Selection data: train only. Reports both unseen events and unseen agencies.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, recall_score
from sklearn.model_selection import GroupKFold


LABELS = ["不予处罚", "拘留", "拘留并处罚款", "罚款"]


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def label(row: dict) -> str:
    value = row["target"]["type"]
    return value if value in LABELS else "不予处罚"


def fit_lr(x, y, weight):
    if len(set(y)) == 1:
        return None, y[0]
    model = LogisticRegression(C=3.0, max_iter=1000, random_state=20261027)
    model.fit(x, y, sample_weight=weight)
    return model, None


def predict_lr(model, constant, x):
    return np.full(x.shape[0], constant) if model is None else model.predict(x)


def score(truth, pred, weights):
    return {"n": len(truth),
            "accuracy": float(accuracy_score(truth, pred)),
            "event_weighted_accuracy": float(accuracy_score(truth, pred, sample_weight=weights)),
            "macro_f1_core4": float(f1_score(truth, pred, labels=LABELS, average="macro", zero_division=0)),
            "recall": {kind: float(recall_score(truth, pred, labels=[kind], average="macro", zero_division=0))
                       for kind in LABELS}}


def experiment(rows, axis):
    texts = [row["input"]["facts_text"] for row in rows]
    truth = np.asarray([label(row) for row in rows])
    events = [row["event_id"] for row in rows]
    agencies = [event.split("|")[0] for event in events]
    groups = events if axis == "event" else agencies
    sizes = Counter(events)
    weights = np.asarray([1 / sizes[event] for event in events], dtype=float)
    flat_pred = np.empty(len(rows), dtype=object)
    factor_pred = np.empty(len(rows), dtype=object)
    folds = []
    for fold, (train, valid) in enumerate(GroupKFold(n_splits=3).split(texts, truth, groups), 1):
        if set(np.asarray(groups)[train]) & set(np.asarray(groups)[valid]):
            raise AssertionError("Group leakage")
        vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3),
                                     sublinear_tf=True, min_df=2, max_features=100_000)
        x_train = vectorizer.fit_transform(texts[i] for i in train)
        x_valid = vectorizer.transform(texts[i] for i in valid)
        y_train = truth[train]
        w_train = weights[train]
        flat, const = fit_lr(x_train, y_train, w_train)
        flat_pred[valid] = predict_lr(flat, const, x_valid)
        det = np.isin(y_train, ["拘留", "拘留并处罚款"]).astype(int)
        fine = np.isin(y_train, ["罚款", "拘留并处罚款"]).astype(int)
        det_model, det_const = fit_lr(x_train, det, w_train)
        fine_model, fine_const = fit_lr(x_train, fine, w_train)
        d_pred = predict_lr(det_model, det_const, x_valid)
        f_pred = predict_lr(fine_model, fine_const, x_valid)
        factor_pred[valid] = ["拘留并处罚款" if d and f else "拘留" if d else "罚款" if f else "不予处罚"
                              for d, f in zip(d_pred, f_pred)]
        folds.append({"fold": fold, "train_records": len(train), "valid_records": len(valid),
                      "train_events": len(set(np.asarray(events)[train])),
                      "valid_events": len(set(np.asarray(events)[valid])),
                      "valid_agencies": len(set(np.asarray(agencies)[valid]))})
    return {"folds": folds, "flat": score(truth, flat_pred, weights),
            "factorized": score(truth, factor_pred, weights),
            "paired": {"flat_only_correct": int(((flat_pred == truth) & (factor_pred != truth)).sum()),
                       "factorized_only_correct": int(((factor_pred == truth) & (flat_pred != truth)).sum())}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    rows = read(args.package / "train.jsonl")
    report = {"package": str(args.package), "selection_data": "train_only",
              "models": {"flat": "char1-3_tfidf_logistic_4class",
                         "factorized": "char1-3_tfidf_two_binary_heads_detention_and_fine"},
              "event_weighting": "inverse_event_size", "seed": 20261027,
              "axes": {axis: experiment(rows, axis) for axis in ("event", "agency")},
              "test_scored": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["axes"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

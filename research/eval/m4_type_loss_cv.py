"""Fixed-fold loss/class weighting comparison on frozen M4 train only."""
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
from sklearn.svm import LinearSVC

from m4_type_algorithm_cv import LABELS, label, read


SPECS = {
    "lr_plain": lambda: LogisticRegression(C=3.0, max_iter=1000, random_state=20261027),
    "lr_balanced": lambda: LogisticRegression(C=3.0, max_iter=1000, class_weight="balanced", random_state=20261027),
    "svm_plain": lambda: LinearSVC(C=0.3, random_state=20261027),
    "svm_balanced": lambda: LinearSVC(C=0.3, class_weight="balanced", random_state=20261027),
}


def run(rows, axis):
    texts = [row["input"]["facts_text"] for row in rows]
    truth = np.asarray([label(row) for row in rows])
    events = [row["event_id"] for row in rows]
    agencies = [event.split("|")[0] for event in events]
    groups = events if axis == "event" else agencies
    counts = Counter(events)
    weights = np.asarray([1 / counts[event] for event in events])
    predictions = {name: np.empty(len(rows), dtype=object) for name in SPECS}
    for train, valid in GroupKFold(n_splits=3).split(texts, truth, groups):
        vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3),
                                     sublinear_tf=True, min_df=2, max_features=100_000)
        x_train = vectorizer.fit_transform(texts[i] for i in train)
        x_valid = vectorizer.transform(texts[i] for i in valid)
        for name, factory in SPECS.items():
            model = factory()
            model.fit(x_train, truth[train], sample_weight=weights[train])
            predictions[name][valid] = model.predict(x_valid)
    metrics = {}
    for name, pred in predictions.items():
        metrics[name] = {
            "accuracy": float(accuracy_score(truth, pred)),
            "event_weighted_accuracy": float(accuracy_score(truth, pred, sample_weight=weights)),
            "macro_f1_core4": float(f1_score(truth, pred, labels=LABELS, average="macro", zero_division=0)),
            "recall": {kind: float(recall_score(truth, pred, labels=[kind], average="macro", zero_division=0))
                       for kind in LABELS},
            "vs_lr_plain": {"gain": int(((pred == truth) & (predictions["lr_plain"] != truth)).sum()),
                            "loss": int(((pred != truth) & (predictions["lr_plain"] == truth)).sum())}
        }
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    rows = read(args.package / "train.jsonl")
    report = {"package": str(args.package), "selection_data": "train_only",
              "specs": list(SPECS), "event_weighting": "inverse_event_size",
              "seed": 20261027, "axes": {axis: run(rows, axis) for axis in ("event", "agency")},
              "test_scored": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({axis: {name: {"macro_f1_core4": block["macro_f1_core4"],
                                    "accuracy": block["accuracy"], "recall": block["recall"]}
                             for name, block in models.items()} for axis, models in report["axes"].items()},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

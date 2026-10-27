"""Pre-registered, ownership-free amount feature ablation for M4 type.

No outcome-derived weak labels enter the features. Amounts are extracted only
from facts_text; train-only event/agency folds remain fixed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, accuracy_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from m4_type_algorithm_cv import LABELS, label, read
from outcome_constraint_calibration import extract_stake_amounts


def amount_features(facts: str) -> list[float]:
    extracted = extract_stake_amounts(facts)
    amounts = [v for values in extracted.values() for v in values]
    if not amounts:
        return [0.0] * 7
    top = max(amounts)
    return [1.0, math.log1p(top), math.log1p(sum(amounts)), math.log1p(len(amounts)),
            float(top >= 500), float(top >= 1000), float(top >= 2000)]


def run(rows, axis):
    texts = [row["input"]["facts_text"] for row in rows]
    numeric = np.asarray([amount_features(text) for text in texts])
    truth = np.asarray([label(row) for row in rows])
    events = [row["event_id"] for row in rows]
    agencies = [event.split("|")[0] for event in events]
    groups = events if axis == "event" else agencies
    sizes = Counter(events)
    weights = np.asarray([1 / sizes[event] for event in events])
    pred = {name: np.empty(len(rows), dtype=object) for name in ("text", "text_amount")}
    for train, valid in GroupKFold(n_splits=3).split(texts, truth, groups):
        vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3),
                                     sublinear_tf=True, min_df=2, max_features=100_000)
        x_train = vectorizer.fit_transform(texts[i] for i in train)
        x_valid = vectorizer.transform(texts[i] for i in valid)
        scaler = StandardScaler()
        a_train = csr_matrix(scaler.fit_transform(numeric[train]))
        a_valid = csr_matrix(scaler.transform(numeric[valid]))
        for name, xt, xv in (("text", x_train, x_valid),
                              ("text_amount", hstack([x_train, a_train]).tocsr(),
                               hstack([x_valid, a_valid]).tocsr())):
            model = LogisticRegression(C=3.0, class_weight="balanced", max_iter=1000,
                                       random_state=20261027)
            model.fit(xt, truth[train], sample_weight=weights[train])
            pred[name][valid] = model.predict(xv)
    observed = (f1_score(truth, pred["text_amount"], labels=LABELS, average="macro", zero_division=0)
                - f1_score(truth, pred["text"], labels=LABELS, average="macro", zero_division=0))
    rng = np.random.default_rng(20261027)
    event_ids = {event: i for i, event in enumerate(sorted(set(events)))}
    row_event_ids = np.asarray([event_ids[event] for event in events])
    exceed = 0
    for _ in range(1000):
        swap = rng.integers(0, 2, size=len(event_ids), dtype=np.int8)[row_event_ids].astype(bool)
        left = np.where(swap, pred["text_amount"], pred["text"])
        right = np.where(swap, pred["text"], pred["text_amount"])
        diff = (f1_score(truth, right, labels=LABELS, average="macro", zero_division=0)
                - f1_score(truth, left, labels=LABELS, average="macro", zero_division=0))
        exceed += abs(diff) >= abs(observed)
    return {"coverage": float((numeric[:, 0] > 0).mean()),
            "paired_event_permutation": {"macro_f1_delta": float(observed),
                                          "two_sided_p": (exceed + 1) / 1001,
                                          "permutations": 1000},
            "models": {name: {"accuracy": float(accuracy_score(truth, predictions)),
                              "macro_f1_core4": float(f1_score(truth, predictions, labels=LABELS,
                                                               average="macro", zero_division=0))}
                       for name, predictions in pred.items()},
            "paired": {"amount_only_correct": int(((pred["text_amount"] == truth) & (pred["text"] != truth)).sum()),
                       "text_only_correct": int(((pred["text_amount"] != truth) & (pred["text"] == truth)).sum())}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    rows = read(args.package / "train.jsonl")
    report = {"package": str(args.package), "selection_data": "train_only",
              "feature": "facts-only amount max/sum/count and fixed bands; no person attribution",
              "comparison": "balanced LR, identical folds and text vectorizer",
              "axes": {axis: run(rows, axis) for axis in ("event", "agency")},
              "test_scored": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["axes"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

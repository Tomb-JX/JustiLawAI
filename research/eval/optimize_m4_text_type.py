"""Bounded, event-grouped development comparison for the M4 text outcome model.

Only train.jsonl participates in selection. The three pinned validation cohorts are
read once for confirmation; the sealed test is never loaded or scored.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold


CORE = ["不予处罚", "拘留", "拘留并处罚款", "罚款"]
COHORTS = ("old168", "lake706_valid70", "p3p7_valid119")
SPECS = [
    ("char1_3_plain", (1, 3), "plain"),
    ("char1_3_event", (1, 3), "event"),
    ("char1_3_class2", (1, 3), "class2"),
    ("char1_3_event_class2", (1, 3), "event_class2"),
    ("char2_4_plain", (2, 4), "plain"),
    ("char2_4_event", (2, 4), "event"),
    ("char2_4_class2", (2, 4), "class2"),
    ("char2_4_event_class2", (2, 4), "event_class2"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def metrics(truth: list[str], pred: list[str], groups: list[str]) -> dict:
    by_group: dict[str, list[float]] = defaultdict(list)
    for actual, guess, group in zip(truth, pred, groups, strict=True):
        by_group[group].append(float(actual == guess))
    return {
        "records": len(truth),
        "correct": sum(a == b for a, b in zip(truth, pred, strict=True)),
        "accuracy": float(accuracy_score(truth, pred)),
        "macro_f1_core4": float(f1_score(truth, pred, labels=CORE, average="macro", zero_division=0)),
        "event_weighted_accuracy": float(np.mean([np.mean(v) for v in by_group.values()])),
        "core_class_recall": {
            label: {"correct": sum(a == label and b == label for a, b in zip(truth, pred, strict=True)),
                    "total": sum(a == label for a in truth)} for label in CORE
        },
    }


def weights(labels: list[str], groups: list[str], mode: str) -> np.ndarray:
    result = np.ones(len(labels), dtype=float)
    if "event" in mode:
        counts = Counter(groups)
        result *= np.array([1.0 / np.sqrt(counts[group]) for group in groups])
    if "class2" in mode:
        counts = Counter(labels)
        median = float(np.median([counts[label] for label in CORE]))
        result *= np.array([min(2.0, np.sqrt(median / counts[label])) for label in labels])
    return result / np.mean(result)


def vectorizer(ngrams: tuple[int, int]) -> TfidfVectorizer:
    return TfidfVectorizer(analyzer="char", ngram_range=ngrams, sublinear_tf=True,
                           min_df=2, max_features=200_000)


def classifier() -> LogisticRegression:
    return LogisticRegression(C=3.0, max_iter=3000, random_state=20261021)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pack", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    manifest_path = a.pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest["train_records"] != 1740 or manifest["test_scored"]:
        raise ValueError("unexpected source pack")
    for name, expected in manifest["outputs"].items():
        if sha(a.pack / name) != expected:
            raise ValueError(f"source pack changed: {name}")
    train = rows(a.pack / "train.jsonl")
    texts = [r["input"]["facts_text"] for r in train]
    labels = [r["target"]["type"] for r in train]
    groups = [r["event_id"] for r in train]
    fold = list(GroupKFold(n_splits=3).split(texts, labels, groups))
    cv_predictions: dict[str, list[str | None]] = {name: [None] * len(train) for name, _, _ in SPECS}
    for train_idx, valid_idx in fold:
        train_texts = [texts[i] for i in train_idx]
        train_labels = [labels[i] for i in train_idx]
        train_groups = [groups[i] for i in train_idx]
        for ngrams in ((1, 3), (2, 4)):
            vec = vectorizer(ngrams)
            xtrain = vec.fit_transform(train_texts)
            xvalid = vec.transform(texts[i] for i in valid_idx)
            for name, spec_ngrams, mode in SPECS:
                if spec_ngrams != ngrams:
                    continue
                model = classifier().fit(xtrain, train_labels,
                                         sample_weight=weights(train_labels, train_groups, mode))
                pred = model.predict(xvalid)
                for i, y in zip(valid_idx, pred, strict=True):
                    cv_predictions[name][i] = str(y)
    cv_results = {}
    for name, _, _ in SPECS:
        pred = cv_predictions[name]
        if any(y is None for y in pred):
            raise ValueError(f"missing CV prediction: {name}")
        result = metrics(labels, pred, groups)
        result["selection_score"] = (result["macro_f1_core4"] + result["event_weighted_accuracy"]) / 2
        cv_results[name] = result
    winner = max((name for name, _, _ in SPECS), key=lambda name: cv_results[name]["selection_score"])
    baseline = "char1_3_plain"
    selected = [baseline] if winner == baseline else [baseline, winner]
    validations = {name: rows(a.pack / f"{name}.jsonl") for name in COHORTS}
    results, predictions, models = {}, {}, {}
    for name in selected:
        _, ngrams, mode = next(spec for spec in SPECS if spec[0] == name)
        vec = vectorizer(ngrams)
        xtrain = vec.fit_transform(texts)
        model = classifier().fit(xtrain, labels, sample_weight=weights(labels, groups, mode))
        cohort_results, cohort_predictions = {}, {}
        for cohort, records in validations.items():
            actual = [r["target"]["type"] for r in records]
            pred = [str(y) for y in model.predict(vec.transform(r["input"]["facts_text"] for r in records))]
            cohort_results[cohort] = metrics(actual, pred, [r["event_id"] for r in records])
            cohort_predictions.update({r["id"]: y for r, y in zip(records, pred, strict=True)})
        results[name] = cohort_results
        predictions[name] = cohort_predictions
        models[name] = {"vectorizer": vec, "classifier": model, "development_silver": True,
                        "release_approved": False}
    a.out.mkdir(parents=True)
    joblib.dump(models, a.out / "models.joblib")
    report = {"status": "development_comparison", "release_approved": False,
              "test_scored": False, "selection_data": "train_only_3fold_event_grouped",
              "source_manifest_sha256": sha(manifest_path), "train_records": len(train),
              "train_events": len(set(groups)), "candidate_specs": [s[0] for s in SPECS],
              "cv_results": cv_results, "selected_candidate": winner,
              "external_validation": results,
              "model_sha256": sha(a.out / "models.joblib")}
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (a.out / "predictions.json").write_text(json.dumps(predictions, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"winner": winner, "cv": {k: v["selection_score"] for k, v in cv_results.items()},
                      "external": {k: {c: v["correct"] for c, v in x.items()} for k, x in results.items()}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

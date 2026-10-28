"""Compare simple text-based amount estimators with event-grouped development CV."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import NearestNeighbors


FIELDS = ("detention_days", "fine")
COHORTS = ("old168", "lake706_valid70", "p3p7_valid119")
METHODS = ("median", "ridge", "knn5", "knn15", "source_median", "source_knn15")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_vec() -> TfidfVectorizer:
    return TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                           min_df=2, max_features=200_000)


def fit_predict(train: list[dict], valid: list[dict]) -> tuple[dict, dict]:
    vec = make_vec()
    xtrain = vec.fit_transform(r["input"]["facts_text"] for r in train)
    xvalid = vec.transform(r["input"]["facts_text"] for r in valid)
    near = NearestNeighbors(n_neighbors=15, metric="cosine", algorithm="brute").fit(xtrain)
    neighbors = near.kneighbors(xvalid, return_distance=False)
    train_sources = [r["metadata"]["cohort"] for r in train]
    valid_sources = [r["metadata"]["cohort"] for r in valid]
    source_neighbors = np.empty((len(valid), 15), dtype=int)
    for source in sorted(set(valid_sources)):
        train_idx = np.array([i for i, value in enumerate(train_sources) if value == source])
        valid_idx = np.array([i for i, value in enumerate(valid_sources) if value == source])
        if len(train_idx) < 15:
            raise ValueError(f"source too small for 15-neighbor estimate: {source}")
        local = NearestNeighbors(n_neighbors=15, metric="cosine", algorithm="brute").fit(xtrain[train_idx])
        source_neighbors[valid_idx] = train_idx[local.kneighbors(xvalid[valid_idx], return_distance=False)]
    outputs, models = {}, {"vectorizer": vec, "neighbors": near,
                          "train_sources": train_sources, "targets": {}}
    for field in FIELDS:
        values = np.array([float(r["target"][field]) for r in train])
        ridge = Ridge(alpha=1.0, solver="lsqr").fit(xtrain, values)
        models["targets"][field] = values
        models[field] = ridge
        outputs[field] = {
            "median": np.full(len(valid), np.median(values)),
            "ridge": np.maximum(0.0, ridge.predict(xvalid)),
            "knn5": np.median(values[neighbors[:, :5]], axis=1),
            "knn15": np.median(values[neighbors], axis=1),
            "source_median": np.array([np.median(values[[i for i, source in enumerate(train_sources)
                                                          if source == wanted]]) for wanted in valid_sources]),
            "source_knn15": np.median(values[source_neighbors], axis=1),
        }
    return outputs, models


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pack", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
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
    cv_predictions = {field: {method: np.empty(len(train)) for method in METHODS} for field in FIELDS}
    groups = [r["event_id"] for r in train]
    for fit_idx, predict_idx in GroupKFold(n_splits=3).split(train, groups=groups):
        fit = [train[i] for i in fit_idx]
        predict = [train[i] for i in predict_idx]
        outputs, _ = fit_predict(fit, predict)
        for field in FIELDS:
            for method in METHODS:
                cv_predictions[field][method][predict_idx] = outputs[field][method]
    cv = {}
    cv_by_source = {}
    for field in FIELDS:
        actual = [float(r["target"][field]) for r in train]
        cv[field] = {method: float(mean_absolute_error(actual, cv_predictions[field][method]))
                     for method in METHODS}
        cv_by_source[field] = {}
        for source in sorted({r["metadata"]["cohort"] for r in train}):
            idx = [i for i, r in enumerate(train) if r["metadata"]["cohort"] == source]
            cv_by_source[field][source] = {
                method: float(mean_absolute_error(np.array(actual)[idx], cv_predictions[field][method][idx]))
                for method in METHODS}
    winners = {field: min(METHODS, key=cv[field].get) for field in FIELDS}
    source_winners = {field: {source: min(METHODS, key=scores.get)
                              for source, scores in cv_by_source[field].items()} for field in FIELDS}
    validations = {cohort: rows(a.pack / f"{cohort}.jsonl") for cohort in COHORTS}
    all_valid = sum(validations.values(), [])
    outputs, models = fit_predict(train, all_valid)
    external = {}
    predictions = {}
    offset = 0
    for cohort, records in validations.items():
        external[cohort] = {}
        predictions[cohort] = {}
        for field in FIELDS:
            actual = np.array([float(r["target"][field]) for r in records])
            external[cohort][field] = {}
            for method in METHODS:
                pred = outputs[field][method][offset:offset + len(records)]
                external[cohort][field][method] = float(mean_absolute_error(actual, pred))
                predictions[cohort][f"{field}_{method}"] = {
                    r["id"]: float(y) for r, y in zip(records, pred, strict=True)}
        offset += len(records)
    a.out.mkdir(parents=True)
    models.update({"development_silver": True, "release_approved": False})
    joblib.dump(models, a.out / "models.joblib")
    report = {"status": "development_comparison", "release_approved": False,
              "test_scored": False, "selection_data": "train_only_3fold_event_grouped",
              "source_manifest_sha256": sha(manifest_path), "train_records": len(train),
              "train_events": len(set(groups)), "cv_mae": cv,
              "cv_mae_by_source": cv_by_source, "selected_methods": winners,
              "selected_methods_by_source": source_winners,
              "external_validation_mae": external,
              "model_sha256": sha(a.out / "models.joblib")}
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (a.out / "predictions.json").write_text(json.dumps(predictions, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"cv_mae": cv, "source_selected": source_winners,
                      "external_mae": external}, ensure_ascii=False))


if __name__ == "__main__":
    main()

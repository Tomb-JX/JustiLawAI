"""One fixed-parameter M4 text comparison after the P3–P7 event-key regroup.

Development silver only. The sealed test is read only for event isolation and is
never scored. This script does not consume L5 fields or call a model API.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import f1_score, mean_absolute_error


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split(row: dict) -> str:
    return row.get("split") or row["metadata"]["split"]


def event(row: dict) -> str:
    return row.get("event_id") or row["metadata"]["event_id"]


def facts(row: dict) -> str:
    return row.get("facts_text") or row["input"]["facts_text"]


def check_metrics(actual: list[str], pred: list[str], source: list[dict],
                  legacy_labels: list[str], all_labels: list[str]) -> dict:
    by_event: dict[str, list[bool]] = defaultdict(list)
    for truth, guess, row in zip(actual, pred, source, strict=True):
        by_event[event(row)].append(truth == guess)
    return {
        "records": len(actual),
        "events": len(by_event),
        "correct": sum(a == b for a, b in zip(actual, pred, strict=True)),
        "macro_f1": float(f1_score(actual, pred, labels=legacy_labels, average="macro", zero_division=0)),
        "macro_f1_all_labels": float(f1_score(actual, pred, labels=all_labels, average="macro", zero_division=0)),
        "macro_f1_present_labels": float(f1_score(actual, pred, labels=sorted(set(actual)), average="macro", zero_division=0)),
        "event_weighted_accuracy": float(np.mean([np.mean(x) for x in by_event.values()])),
        "classes": {label: {
            "n": sum(x == label for x in actual),
            "correct": sum(a == label and b == label for a, b in zip(actual, pred, strict=True)),
        } for label in sorted(set(actual))},
    }


def main() -> None:
    p = argparse.ArgumentParser()
    for name in ("base", "prior85", "lake706", "p3p7", "queue", "regroup", "sealed203"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    paths = {name: getattr(a, name) for name in
             ("base", "prior85", "lake706", "p3p7", "queue", "regroup", "sealed203")}
    base, prior, lake, p3, sealed = (rows(paths[name]) for name in
                                    ("base", "prior85", "lake706", "p3p7", "sealed203"))
    queue = {r["id"]: (r["source_batch"], r["source_id"]) for r in rows(paths["queue"])}
    regroup = {(r["batch"], r["id"]): r["new"] for r in rows(paths["regroup"])}
    if len(queue) != 655 or len(regroup) != 522:
        raise ValueError("P3–P7 queue or regroup source changed")
    changed = 0
    for row in p3:
        new = regroup.get(queue[row["id"]], row["event_id"])
        changed += new != row["event_id"]
        row["event_id"] = new
    base_train = [r for r in base if split(r) == "train"]
    base_valid = [r for r in base if split(r) == "valid"]
    prior_train = [r for r in prior if split(r) == "train"]
    lake_train = [r for r in lake if split(r) == "train"]
    lake_valid = [r for r in lake if split(r) == "valid"]
    p3_train = [r for r in p3 if split(r) == "train"]
    p3_valid = [r for r in p3 if split(r) == "valid"]
    sealed_test = [r for r in sealed if split(r) == "test"]
    actual_counts = tuple(map(len, (base_train, base_valid, prior_train, lake_train,
                                    lake_valid, p3_train, p3_valid, sealed_test)))
    if actual_counts != (868, 168, 85, 275, 70, 512, 119, 40):
        raise ValueError(f"frozen cohort counts changed: {actual_counts}")
    all_rows = base_train + base_valid + prior_train + lake_train + lake_valid + p3_train + p3_valid + sealed_test
    ids = [r["id"] for r in all_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate record ID across cohorts")
    train_events = {event(r) for r in base_train + prior_train + lake_train + p3_train}
    holdout_events = {event(r) for r in base_valid + lake_valid + p3_valid + sealed_test}
    if train_events & holdout_events:
        raise ValueError("train/holdout event overlap after regroup")
    if {event(r) for r in p3_train} & {event(r) for r in p3_valid}:
        raise ValueError("P3–P7 train/valid event overlap")

    cohorts = {"old168": base_valid, "lake706_valid70": lake_valid,
               "p3p7_valid119": p3_valid}
    all_valid = base_valid + lake_valid + p3_valid
    legacy_labels = sorted({r["observed_outcome"]["type"] for r in base_train + base_valid})
    all_labels = sorted({r["observed_outcome"]["type"] for r in
                         base_train + base_valid + prior_train + lake_train + lake_valid + p3_train + p3_valid})
    results: dict[str, dict] = {}
    predictions: dict[str, dict[str, str]] = {}
    expanded_bundle: dict = {}
    for name, train in (("existing1228", base_train + prior_train + lake_train),
                        ("with_p3p7_1740", base_train + prior_train + lake_train + p3_train)):
        vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                              min_df=2, max_features=200_000)
        xtrain = vec.fit_transform(facts(r) for r in train)
        xvalid = vec.transform(facts(r) for r in all_valid)
        ytrain = [r["observed_outcome"]["type"] for r in train]
        classifier = LogisticRegression(C=3.0, max_iter=3000, random_state=20261021).fit(xtrain, ytrain)
        pred = classifier.predict(xvalid)
        predictions[name] = {r["id"]: str(y) for r, y in zip(all_valid, pred, strict=True)}
        result = {"train_records": len(train), "train_events": len({event(r) for r in train}),
                  "cohorts": {}}
        offset = 0
        for cohort, valid in cohorts.items():
            ys = [r["observed_outcome"]["type"] for r in valid]
            yp = [str(v) for v in pred[offset:offset + len(valid)]]
            offset += len(valid)
            result["cohorts"][cohort] = check_metrics(ys, yp, valid, legacy_labels, all_labels)
        for field in ("detention_days", "fine"):
            target = [float(r["observed_outcome"][field]) for r in train]
            regressor = Ridge(alpha=1.0, solver="lsqr").fit(xtrain, target)
            estimates = np.maximum(0.0, regressor.predict(xvalid))
            if name == "with_p3p7_1740":
                expanded_bundle[field] = regressor
            median = float(np.median(target))
            offset = 0
            for cohort, valid in cohorts.items():
                actual = [float(r["observed_outcome"][field]) for r in valid]
                part = estimates[offset:offset + len(valid)]
                offset += len(valid)
                result["cohorts"][cohort][field] = {
                    "mae": float(mean_absolute_error(actual, part)),
                    "train_median_baseline_mae": float(mean_absolute_error(actual, [median] * len(actual))),
                }
        results[name] = result
        if name == "with_p3p7_1740":
            expanded_bundle.update({"vectorizer": vec, "type_classifier": classifier,
                                    "release_approved": False, "development_silver": True})
    paired = {}
    for cohort, valid in cohorts.items():
        old_only = new_only = 0
        for row in valid:
            truth = row["observed_outcome"]["type"]
            old = predictions["existing1228"][row["id"]] == truth
            new = predictions["with_p3p7_1740"][row["id"]] == truth
            old_only += old and not new
            new_only += new and not old
        paired[cohort] = {"existing_only_correct": old_only, "expanded_only_correct": new_only}
    report = {"status": "development_silver_only", "test_scored": False,
              "model_parameters_frozen": True, "p3p7_regrouped_records": changed,
              "macro_f1_legacy_labels": legacy_labels,
              "macro_f1_all_labels": all_labels,
              "p3p7_train_events_after_regroup": len({event(r) for r in p3_train}),
              "p3p7_valid_events_after_regroup": len({event(r) for r in p3_valid}),
              "sources": {k: {"path": str(v), "sha256": sha(v)} for k, v in paths.items()},
              "results": results, "paired": paired}
    a.out.mkdir(parents=True)
    joblib.dump(expanded_bundle, a.out / "models.joblib")
    report["model_artifact"] = {"path": "models.joblib", "sha256": sha(a.out / "models.joblib"),
                                "release_approved": False}
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (a.out / "predictions.json").write_text(json.dumps(predictions, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"paired": paired, "results": {
        name: {cohort: {k: v for k, v in x.items() if k in ("correct", "macro_f1", "event_weighted_accuracy")}
               for cohort, x in result["cohorts"].items()} for name, result in results.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

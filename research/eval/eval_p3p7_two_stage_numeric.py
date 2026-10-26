"""Fixed two-stage detention/fine pilot on the pinned 1740-record text cohort."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import f1_score, mean_absolute_error


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def facts(row: dict) -> str:
    return row.get("facts_text") or row["input"]["facts_text"]


def split(row: dict) -> str:
    return row.get("split") or row["metadata"]["split"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--text-report", type=Path, required=True)
    p.add_argument("--text-model", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    text_report = json.loads(a.text_report.read_text("utf-8"))
    sources = {k: Path(v["path"]) for k, v in text_report["sources"].items()}
    if any(sha(path) != text_report["sources"][k]["sha256"] for k, path in sources.items()):
        raise ValueError("text experiment source changed")
    base, prior, lake, p3 = (rows(sources[k]) for k in ("base", "prior85", "lake706", "p3p7"))
    train = ([r for r in base if split(r) == "train"] +
             [r for r in prior if split(r) == "train"] +
             [r for r in lake if split(r) == "train"] +
             [r for r in p3 if split(r) == "train"])
    cohorts = {"old168": [r for r in base if split(r) == "valid"],
               "lake706_valid70": [r for r in lake if split(r) == "valid"],
               "p3p7_valid119": [r for r in p3 if split(r) == "valid"]}
    if len(train) != 1740 or tuple(map(len, cohorts.values())) != (168, 70, 119):
        raise ValueError("cohort changed")
    bundle = joblib.load(a.text_model)
    if bundle["release_approved"] is not False or sha(a.text_model) != text_report["model_artifact"]["sha256"]:
        raise ValueError("text model artifact changed")
    vec = bundle["vectorizer"]
    xtrain = vec.transform(facts(r) for r in train)
    results = {}
    models = {}
    for field in ("detention_days", "fine"):
        target = np.array([float(r["observed_outcome"][field]) for r in train])
        positive = target > 0
        clf = LogisticRegression(C=3.0, max_iter=3000, random_state=20261021).fit(xtrain, positive)
        conditional = Ridge(alpha=1.0, solver="lsqr").fit(xtrain[positive], target[positive])
        models[field] = {"positive_classifier": clf, "conditional_regressor": conditional}
        field_results = {}
        for cohort, valid in cohorts.items():
            xvalid = vec.transform(facts(r) for r in valid)
            actual = np.array([float(r["observed_outcome"][field]) for r in valid])
            has = clf.predict(xvalid)
            hurdle = np.where(has, np.maximum(0.0, conditional.predict(xvalid)), 0.0)
            single = np.maximum(0.0, bundle[field].predict(xvalid))
            median = float(np.median(target))
            field_results[cohort] = {
                "records": len(valid), "positive_truth": int((actual > 0).sum()),
                "positive_predicted": int(has.sum()),
                "positive_f1": float(f1_score(actual > 0, has, zero_division=0)),
                "single_ridge_mae": float(mean_absolute_error(actual, single)),
                "two_stage_mae": float(mean_absolute_error(actual, hurdle)),
                "median_constant_mae": float(mean_absolute_error(actual, np.full(len(actual), median))),
                "two_stage_positive_truth_mae": float(mean_absolute_error(actual[actual > 0], hurdle[actual > 0])) if (actual > 0).any() else None,
                "two_stage_zero_truth_mae": float(mean_absolute_error(actual[actual == 0], hurdle[actual == 0])) if (actual == 0).any() else None,
            }
        results[field] = field_results
    a.out.mkdir(parents=True)
    model_path = a.out / "models.joblib"
    joblib.dump({"release_approved": False, "development_silver": True, "models": models}, model_path)
    report = {"status": "fixed_two_stage_development_pilot", "release_approved": False,
              "test_scored": False, "train_records": len(train), "parameters_frozen": True,
              "source_text_report_sha256": sha(a.text_report), "source_text_model_sha256": sha(a.text_model),
              "models_sha256": sha(model_path), "results": results}
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()

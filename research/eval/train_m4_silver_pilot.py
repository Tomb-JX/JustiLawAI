"""Train a fixed structured M4 development baseline on the reviewed silver table.

This is a train/validation experiment. Held-out test rows are used only for
split integrity checks; they never enter the feature extractor or estimator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import joblib
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, precision_recall_fscore_support


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features(row: dict) -> dict[str, float]:
    """Use facts-derived elements only; evidence, target and outcome are excluded."""
    out: dict[str, float] = {}
    for group, fields in row["reference_elements"].items():
        for name, item in fields.items():
            key = f"{group}.{name}"
            status = item["status"]
            out[f"{key}:present"] = float(status != "未提及")
            if status == "未提及":
                continue
            value = item.get("value")
            if isinstance(value, bool):
                out[f"{key}:true"] = float(value)
            elif isinstance(value, (int, float)):
                out[f"{key}:value"] = math.log1p(max(0.0, float(value)))
            elif isinstance(value, str):
                out[f"{key}:category={value}"] = 1.0
            elif isinstance(value, dict):
                for bound in ("min", "max"):
                    number = value.get(bound)
                    if isinstance(number, (int, float)):
                        out[f"{key}:{bound}"] = math.log1p(max(0.0, float(number)))
                out[f"{key}:open"] = float(value.get("max") is None)
    # Channel is a source-quality covariate available at deployment time.
    channel = row.get("metadata", {}).get("channel")
    if channel:
        out[f"channel={channel}"] = 1.0
    return out


def run(data_path: Path, silver_manifest: Path, out_dir: Path) -> dict:
    manifest = json.loads(silver_manifest.read_text("utf-8"))
    if manifest["g22"]["overall"] != "conditional_silver_training_only; G2.2 formal release NOT passed":
        raise ValueError("unexpected quality evidence status; review the training policy")
    table_manifest = json.loads(data_path.with_name("manifest.json").read_text("utf-8"))
    if table_manifest["sources"]["labels"]["sha256"] != manifest["sources"]["silver"]["sha256"]:
        raise ValueError("M4 table does not use the audited silver labels")
    if table_manifest["sources"]["records"]["sha256"] != digest(data_path):
        raise ValueError("M4 table hash mismatch")
    rows = [json.loads(line) for line in data_path.read_text("utf-8").splitlines() if line.strip()]
    train = [r for r in rows if r["metadata"]["split"] == "train"]
    valid = [r for r in rows if r["metadata"]["split"] == "valid"]
    test_count = sum(r["metadata"]["split"] == "test" for r in rows)
    if (len(rows), len(train), len(valid), test_count) != (203, 140, 23, 40):
        raise ValueError("unexpected frozen split")
    if any(r["label_provenance"] != "manual-silver" or r["human_review"] for r in rows):
        raise ValueError("unexpected label provenance")
    events = {split: {r["metadata"]["event_id"] for r in rows if r["metadata"]["split"] == split}
              for split in ("train", "valid", "test")}
    if any(events[a] & events[b] for a, b in (("train", "valid"), ("train", "test"), ("valid", "test"))):
        raise ValueError("event overlap across splits")
    vectorizer = DictVectorizer(sparse=True)
    x_train = vectorizer.fit_transform(features(r) for r in train)
    x_valid = vectorizer.transform(features(r) for r in valid)
    y_train = [r["observed_outcome"]["type"] for r in train]
    y_valid = [r["observed_outcome"]["type"] for r in valid]
    classifier = LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced", random_state=20261020)
    classifier.fit(x_train, y_train)
    prediction = classifier.predict(x_valid)
    labels = sorted(set(y_train) | set(y_valid))
    p, recall, f1, support = precision_recall_fscore_support(
        y_valid, prediction, labels=labels, zero_division=0
    )
    metrics = {
        "accuracy": float(accuracy_score(y_valid, prediction)),
        "macro_f1": float(f1_score(y_valid, prediction, labels=labels, average="macro", zero_division=0)),
        "by_class": {label: {"precision": float(p[i]), "recall": float(recall[i]),
                             "f1": float(f1[i]), "support": int(support[i])}
                     for i, label in enumerate(labels)},
    }
    regressors = {}
    for field in ("detention_days", "fine"):
        target_train = [float(r["observed_outcome"][field] or 0) for r in train]
        target_valid = [float(r["observed_outcome"][field] or 0) for r in valid]
        model = Ridge(alpha=10.0, solver="lsqr")
        model.fit(x_train, target_train)
        pred = [max(0.0, float(v)) for v in model.predict(x_valid)]
        metrics[field] = {"mae": float(mean_absolute_error(target_valid, pred))}
        regressors[field] = model
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.joblib"
    joblib.dump({"vectorizer": vectorizer, "classifier": classifier,
                 "regressors": regressors, "release_approved": False}, model_path)
    report = {
        "status": "development_silver_only", "test_evaluated": False,
        "input_sha256": digest(data_path), "silver_manifest_sha256": digest(silver_manifest),
        "model_sha256": digest(model_path), "split": {"train": 140, "valid": 23, "test_sealed": 40},
        "features": len(vectorizer.feature_names_), "train_types": dict(Counter(y_train)),
        "valid_types": dict(Counter(y_valid)), "metrics": metrics,
        "configuration": {"classifier": "LogisticRegression(C=1, class_weight=balanced)",
                          "regressors": "Ridge(alpha=10)", "random_seed": 20261020},
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


def main() -> None:
    root = Path(r"D:/02_Dev/Data/justilaw-research")
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=root / "parsed2/m4-pilot-203-silver-20261020/records.jsonl")
    parser.add_argument("--silver-manifest", type=Path, default=root / "s1_runs/manual-batches/ALL-203-silver-20261020/manifest.json")
    parser.add_argument("--out", type=Path, default=root / "engine/development/m4-silver-pilot-20261020")
    args = parser.parse_args()
    print(json.dumps(run(args.data, args.silver_manifest, args.out)["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()

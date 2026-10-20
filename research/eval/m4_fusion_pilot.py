"""One fixed text + silver-element M4 development comparison; never score test."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
from scipy.sparse import hstack
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error
from sklearn.preprocessing import Normalizer

from train_m4_silver_pilot import features


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(data_path: Path, out_dir: Path) -> dict:
    table = json.loads(data_path.with_name("manifest.json").read_text("utf-8"))
    if table["sources"]["records"]["sha256"] != sha(data_path):
        raise ValueError("frozen M4 table hash mismatch")
    rows = [json.loads(line) for line in data_path.read_text("utf-8").splitlines() if line.strip()]
    train = [r for r in rows if r["metadata"]["split"] == "train"]
    valid = [r for r in rows if r["metadata"]["split"] == "valid"]
    sealed = [r for r in rows if r["metadata"]["split"] == "test"]
    if (len(train), len(valid), len(sealed)) != (140, 23, 40):
        raise ValueError("unexpected split")
    events = [{r["metadata"]["event_id"] for r in part} for part in (train, valid, sealed)]
    if any(events[i] & events[j] for i, j in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("event crosses split")
    if any(r["label_provenance"] != "manual-silver" for r in train + valid):
        raise ValueError("unexpected label provenance")

    text_vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3),
                               sublinear_tf=True, min_df=2, max_features=200_000)
    elem_vec = DictVectorizer(sparse=True)
    elem_norm = Normalizer()
    xtr_text = text_vec.fit_transform(r["input"].get("facts_text") or "" for r in train)
    xva_text = text_vec.transform(r["input"].get("facts_text") or "" for r in valid)
    xtr_elem = elem_norm.fit_transform(elem_vec.fit_transform(features(r) for r in train))
    xva_elem = elem_norm.transform(elem_vec.transform(features(r) for r in valid))
    # Each block has unit L2 norm. This equal-weight concatenation is fixed a priori.
    xtr = hstack((xtr_text, xtr_elem), format="csr")
    xva = hstack((xva_text, xva_elem), format="csr")
    ytr = [r["observed_outcome"]["type"] for r in train]
    yva = [r["observed_outcome"]["type"] for r in valid]
    classifier = LogisticRegression(C=3.0, max_iter=3000)
    classifier.fit(xtr, ytr)
    pred = classifier.predict(xva)
    report = {
        "status": "development_silver_only", "test_evaluated": False,
        "data_sha256": sha(data_path), "split": {"train": 140, "valid": 23, "test_sealed": 40},
        "features": {"text": xtr_text.shape[1], "elements": xtr_elem.shape[1]},
        "configuration": {"text": "char TF-IDF 1-3, min_df=2, sublinear_tf",
                          "elements": "DictVectorizer + row L2 normalization",
                          "fusion": "equal-weight concatenation",
                          "classifier": "LogisticRegression(C=3)",
                          "regressors": "Ridge(alpha=1)"},
        "classification": {
            "accuracy": float(accuracy_score(yva, pred)),
            "macro_f1": float(f1_score(yva, pred, labels=sorted(set(ytr) | set(yva)),
                                       average="macro", zero_division=0)),
            "correct": int(sum(a == b for a, b in zip(pred, yva, strict=True))),
        },
        "numeric": {},
    }
    regressors = {}
    for field in ("detention_days", "fine"):
        target_tr = [float(r["observed_outcome"][field] or 0) for r in train]
        target_va = [float(r["observed_outcome"][field] or 0) for r in valid]
        model = Ridge(alpha=1.0, solver="lsqr")
        model.fit(xtr, target_tr)
        estimate = [max(0.0, float(v)) for v in model.predict(xva)]
        report["numeric"][field] = {
            "mae": float(mean_absolute_error(target_va, estimate)),
            "within_20pct": float(sum(abs(p - y) <= .2 * y if y else p < .5
                                        for p, y in zip(estimate, target_va, strict=True)) / len(target_va)),
        }
        regressors[field] = model
    out_dir.mkdir(parents=True, exist_ok=True)
    model_file = out_dir / "model.joblib"
    joblib.dump({"text_vectorizer": text_vec, "element_vectorizer": elem_vec,
                 "element_normalizer": elem_norm, "classifier": classifier,
                 "regressors": regressors, "release_approved": False}, model_file)
    report["model_sha256"] = sha(model_file)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


def main() -> None:
    root = Path(r"D:/02_Dev/Data/justilaw-research")
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=root / "parsed2/m4-pilot-203-silver-20261020/records.jsonl")
    ap.add_argument("--out", type=Path, default=root / "engine/development/m4-fusion-pilot-20261021")
    args = ap.parse_args()
    report = run(args.data, args.out)
    print(json.dumps({"classification": report["classification"], "numeric": report["numeric"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

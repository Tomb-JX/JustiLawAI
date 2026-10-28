"""Check that the materialized text pack reproduces the pinned development model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pack", type=Path, required=True)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    manifest = json.loads((a.pack / "manifest.json").read_text("utf-8"))
    for name, expected in manifest["outputs"].items():
        if sha(a.pack / name) != expected:
            raise ValueError(f"trainset artifact changed: {name}")
    train = rows(a.pack / "train.jsonl")
    if len(train) != 1740 or any(set(r["input"]) != {"facts_text"} for r in train):
        raise ValueError("trainset feature or count changed")
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                          min_df=2, max_features=200_000)
    xtrain = vec.fit_transform(r["input"]["facts_text"] for r in train)
    clf = LogisticRegression(C=3.0, max_iter=3000, random_state=20261021).fit(
        xtrain, [r["target"]["type"] for r in train])
    pinned = json.loads(a.predictions.read_text("utf-8"))["with_p3p7_1740"]
    cohorts = {}
    for name in ("old168", "lake706_valid70", "p3p7_valid119"):
        valid = rows(a.pack / f"{name}.jsonl")
        actual = clf.predict(vec.transform(r["input"]["facts_text"] for r in valid))
        mismatches = [r["id"] for r, y in zip(valid, actual, strict=True) if str(y) != pinned[r["id"]]]
        cohorts[name] = {"records": len(valid), "prediction_mismatch": len(mismatches),
                         "mismatch_ids": mismatches}
    result = {"status": "reproduced" if all(not v["prediction_mismatch"] for v in cohorts.values()) else "mismatch",
              "train_records": len(train), "feature_count": len(vec.vocabulary_),
              "source_manifest_sha256": sha(a.pack / "manifest.json"),
              "source_predictions_sha256": sha(a.predictions), "cohorts": cohorts}
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": result["status"], "train_records": result["train_records"],
                      "mismatches": {k: v["prediction_mismatch"] for k, v in cohorts.items()}}, ensure_ascii=False))
    if result["status"] != "reproduced":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

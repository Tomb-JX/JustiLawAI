"""One-pass, frozen-train comparison of text and hierarchical issuing-agency priors.

The prior sees only earlier decisions in the training fold.  No S1 labels are
regenerated, no provincial rule outputs are used, and test40 stays sealed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.model_selection import GroupKFold

from agency_prior import AgencyPrior, ROOT, load_contexts
from m4_type_algorithm_cv import LABELS, label, read


SMOOTHING_EVENTS = 20.0
PRIOR_STRENGTH = 0.5
FORWARD_CUTOFF = date(2024, 1, 1)
ARMS = ("text", "text_plus_province", "text_plus_city", "text_plus_agency")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fuse(base: np.ndarray, classes: np.ndarray, prior) -> str:
    if prior.probabilities is None or prior.global_probabilities is None:
        return str(classes[np.argmax(base)])
    adjusted = np.array([base[j] * (prior.probabilities[y] /
                         prior.global_probabilities[y]) ** PRIOR_STRENGTH
                         for j, y in enumerate(classes)])
    return str(classes[np.argmax(adjusted)])


def _metrics(y, prediction, indices, event_weights):
    indices = np.asarray(indices, dtype=int)
    if not len(indices):
        return {"n": 0}
    truth, predicted = y[indices], prediction[indices]
    return {"n": int(len(indices)),
            "accuracy": float(accuracy_score(truth, predicted)),
            "event_weighted_accuracy": float(accuracy_score(
                truth, predicted, sample_weight=event_weights[indices])),
            "macro_f1_core4": float(f1_score(
                truth, predicted, labels=LABELS, average="macro", zero_division=0)),
            "recall": {kind: float(recall_score(
                truth, predicted, labels=[kind], average="macro", zero_division=0))
                       for kind in LABELS},
            "fine_detention_cross_errors": int(sum(
                (truth == "罚款") & (predicted == "拘留")) + sum(
                (truth == "拘留") & (predicted == "罚款")))}


def _event_bootstrap(y, base, candidate, indices, events, *, draws=2000, seed=20261027):
    groups = {}
    for i in indices:
        groups.setdefault(events[i], []).append(i)
    units = list(groups.values())
    if not units:
        return None
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(draws):
        sample = [i for j in rng.integers(0, len(units), len(units)) for i in units[j]]
        deltas.append(float(np.mean(candidate[sample] == y[sample]) -
                            np.mean(base[sample] == y[sample])))
    return {"accuracy_delta": float(np.mean(candidate[indices] == y[indices]) -
                                    np.mean(base[indices] == y[indices])),
            "percentile_95": [float(x) for x in np.quantile(deltas, [0.025, 0.975])],
            "event_groups": len(units), "draws": draws}


def evaluate_axis(rows, contexts, axis):
    texts = [r["input"]["facts_text"] for r in rows]
    y = np.asarray([label(r) for r in rows])
    events = np.asarray([r["event_id"] for r in rows])
    agencies = np.asarray([contexts[r["id"]].authority_id or "missing" for r in rows])
    sizes = Counter(events)
    weights = np.asarray([1 / sizes[e] for e in events])
    if axis == "forward":
        train = np.array([i for i, r in enumerate(rows) if contexts[r["id"]].decision_date
                          and contexts[r["id"]].decision_date < FORWARD_CUTOFF], dtype=int)
        valid = np.array([i for i, r in enumerate(rows) if contexts[r["id"]].decision_date
                          and contexts[r["id"]].decision_date >= FORWARD_CUTOFF], dtype=int)
        splits = [(train, valid)]
    else:
        groups = events if axis == "event" else agencies
        splits = list(GroupKFold(n_splits=3).split(texts, y, groups))
    predictions = {arm: np.empty(len(rows), dtype=object) for arm in ARMS}
    prior_predictions = np.empty(len(rows), dtype=object)
    provenance = {}
    valid_all = []
    fold_sizes = []
    for fold, (train, valid) in enumerate(splits, 1):
        if set(events[train]) & set(events[valid]):
            raise AssertionError("event leakage across a model fold")
        if axis == "agency" and set(agencies[train]) & set(agencies[valid]):
            raise AssertionError("agency leakage across a cold-start fold")
        vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                              min_df=2, max_features=100_000)
        xt = vec.fit_transform(texts[i] for i in train)
        xv = vec.transform(texts[i] for i in valid)
        model = LogisticRegression(C=3.0, max_iter=1000, class_weight="balanced",
                                   random_state=20261027)
        model.fit(xt, y[train], sample_weight=weights[train])
        text_probabilities = model.predict_proba(xv)
        prior = AgencyPrior(rows, contexts, train, smoothing_events=SMOOTHING_EVENTS)
        for position, i in enumerate(valid):
            p = text_probabilities[position]
            predictions["text"][i] = model.classes_[np.argmax(p)]
            context = contexts[rows[i]["id"]]
            for level in ("province", "city", "agency"):
                result = prior.predict(context, max_level=level)
                predictions[f"text_plus_{level}"][i] = _fuse(p, model.classes_, result)
                if level == "agency":
                    prior_predictions[i] = (max(LABELS, key=result.probabilities.get)
                                            if result.probabilities else None)
                    provenance[i] = {"source_level": result.source_level,
                                     "effective_events": result.effective_events,
                                     "authority_source": context.authority_source,
                                     "location_source": context.location_source,
                                     "decision_epoch": context.decision_epoch}
        valid_all.extend(valid.tolist())
        fold_sizes.append({"fold": fold, "train": int(len(train)), "valid": int(len(valid))})
    selected = np.asarray(sorted(valid_all), dtype=int)
    seen = np.asarray([i for i in selected if provenance[i]["source_level"] == "agency"], dtype=int)
    fallback = np.asarray([i for i in selected if provenance[i]["source_level"] != "agency"], dtype=int)
    available = np.asarray([i for i in selected if prior_predictions[i] is not None], dtype=int)
    slices = {"all": selected, "agency_history_available": seen,
              "agency_fallback": fallback, "any_prior_available": available}
    by_arm = {arm: {name: _metrics(y, predictions[arm], ids, weights)
                    for name, ids in slices.items()}
              for arm in ARMS}
    by_arm["prior_only"] = {"any_prior_available": _metrics(y, prior_predictions, available, weights)}
    gains = {name: {"candidate_only_correct": int(sum(
                (predictions[name][selected] == y[selected]) &
                (predictions["text"][selected] != y[selected]))),
                    "text_only_correct": int(sum(
                (predictions[name][selected] != y[selected]) &
                (predictions["text"][selected] == y[selected]))),
                    "event_bootstrap_accuracy_delta": _event_bootstrap(
                        y, predictions["text"], predictions[name], selected, events)}
             for name in ARMS if name != "text"}
    return {"axis": axis, "folds": fold_sizes, "model": "weighted_char_tfidf_balanced_LR_C3",
            "population": {"n": int(len(selected)),
                           "source_level": dict(Counter(provenance[i]["source_level"] for i in selected)),
                           "agency_history_available": int(len(seen)),
                           "agency_fallback": int(len(fallback)),
                           "decision_epoch": dict(Counter(provenance[i]["decision_epoch"] for i in selected))},
            "arms": by_arm, "paired": gains,
            "text_confusion_labels": LABELS,
            "text_confusion": confusion_matrix(y[selected], predictions["text"][selected],
                                                 labels=LABELS).tolist()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path,
                        default=ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    rows = read(args.package / "train.jsonl")
    contexts, context_audit = load_contexts(rows)
    report = {"scope": "frozen_v5_train_only; test40_never_opened",
              "package": str(args.package),
              "train_sha256": _sha(args.package / "train.jsonl"),
              "manifest_sha256": _sha(args.package / "manifest.json"),
              "context": context_audit,
              "configuration": {"smoothing_equivalent_events": SMOOTHING_EVENTS,
                                "fusion_prior_ratio_exponent": PRIOR_STRENGTH,
                                "forward_valid_from": FORWARD_CUTOFF.isoformat(),
                                "decision_history_strictly_earlier": True,
                                "no_probability_calibration_claim": True},
              "axes": {axis: evaluate_axis(rows, contexts, axis)
                       for axis in ("event", "agency", "forward")}}
    args.out.mkdir(parents=True)
    (args.out / "context.jsonl").write_text("".join(
        json.dumps(contexts[row["id"]].serializable(), ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"context": report["context"]["counts"],
                      "axes": {axis: {"population": block["population"],
                                      "arms": {arm: arm_result.get("all", arm_result.get("any_prior_available"))
                                               for arm, arm_result in block["arms"].items()}}
                               for axis, block in report["axes"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

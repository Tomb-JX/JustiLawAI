"""Train-only proof of what provincial M2 suggestions can and cannot add.

No parameter search: the advisory multiplier is fixed at 2 before evaluation.
The 2026-10-27 frozen test40 is never opened. All model predictions are out of
fold by event or agency; provincial suggestions are not treated as legal truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold

from m4_binding_law_ablation import ROOT, prepare_reference, rule_features
from m4_type_algorithm_cv import LABELS, label, read
from outcome_constraint_calibration import resolve_regions

from sys import path as sys_path
sys_path.insert(0, str(Path(__file__).resolve().parents[2] / "justilaw-api"))
from app.discretion.norm_store import load  # noqa: E402

MULTIPLIER = 2.0


def evaluate(y, prediction, mask):
    ids = np.flatnonzero(mask)
    return {"n": int(len(ids)),
            "accuracy": float(accuracy_score(y[ids], prediction[ids])) if len(ids) else None,
            "macro_f1_core4": float(f1_score(y[ids], prediction[ids], labels=LABELS,
                                              average="macro", zero_division=0)) if len(ids) else None}


def event_bootstrap_delta(y, before, after, indices, events, seed=20261027, draws=4000):
    """Case-weighted accuracy delta, resampling whole events; descriptive only."""
    grouped = {}
    for i in indices:
        grouped.setdefault(events[i], []).append(i)
    groups = list(grouped.values())
    if not groups:
        return None
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(draws):
        sample = [i for j in rng.integers(0, len(groups), len(groups)) for i in groups[j]]
        differences.append(float(np.mean(after[sample] == y[sample]) -
                                 np.mean(before[sample] == y[sample])))
    return {"point": float(np.mean(after[indices] == y[indices]) -
                            np.mean(before[indices] == y[indices])),
            "percentile_95": [float(x) for x in np.quantile(differences, [0.025, 0.975])],
            "draws": draws, "independent_groups": len(groups)}


def shuffled_suggestion_control(y, base, soft, probabilities, classes,
                                eligible, allowed_sets, seed=20261027, draws=4000):
    """Shuffle suggestion sets over the same cases; exploratory specificity check."""
    if not len(eligible):
        return None
    baseline = float(np.mean(base[eligible] == y[eligible]))
    observed = float(np.mean(soft[eligible] == y[eligible]) - baseline)
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(draws):
        shuffled = rng.permutation(len(eligible))
        correct = 0
        for position, i in enumerate(eligible):
            allowed = allowed_sets[shuffled[position]]
            adjusted = probabilities[i].copy()
            for j, name in enumerate(classes):
                if name in allowed:
                    adjusted[j] *= MULTIPLIER
            correct += classes[np.argmax(adjusted)] == y[i]
        null.append(correct / len(eligible) - baseline)
    return {"observed_delta": observed,
            "shuffled_mean_delta": float(np.mean(null)),
            "shuffled_percentile_95": [float(x) for x in np.quantile(null, [0.025, 0.975])],
            "tail_fraction_at_least_observed": float((sum(x >= observed - 1e-12 for x in null) + 1) / (draws + 1)),
            "draws": draws,
            "caution": "Exploratory case-label shuffle; correlated cases and class imbalance limit causal interpretation."}


def run_axis(rows, y, diagnostics, axis):
    texts = [r["input"]["facts_text"] for r in rows]
    events = [r["event_id"] for r in rows]
    groups = events if axis == "event" else [e.split("|")[0] for e in events]
    size = Counter(events)
    weight = np.array([1 / size[e] for e in events])
    base = np.empty(len(rows), dtype=object)
    soft = np.empty(len(rows), dtype=object)
    probabilities = np.zeros((len(rows), len(LABELS)))
    for train, valid in GroupKFold(n_splits=3).split(texts, y, groups):
        assert not set(np.array(groups)[train]) & set(np.array(groups)[valid])
        vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                              min_df=2, max_features=100_000)
        xt = vec.fit_transform(texts[i] for i in train)
        xv = vec.transform(texts[i] for i in valid)
        model = LogisticRegression(C=3.0, max_iter=1000, class_weight="balanced",
                                   random_state=20261027)
        model.fit(xt, y[train], sample_weight=weight[train])
        probability = model.predict_proba(xv)
        for position, i in enumerate(valid):
            p = probability[position]
            probabilities[i] = [p[list(model.classes_).index(name)] if name in model.classes_ else 0.0
                                for name in LABELS]
            base[i] = model.classes_[np.argmax(p)]
            d = diagnostics[rows[i]["id"]]
            if d["status"] != "applicable":
                soft[i] = base[i]
                continue
            adjusted = p.copy()
            for j, name in enumerate(model.classes_):
                if name in d["allowed"]:
                    adjusted[j] *= MULTIPLIER
            soft[i] = model.classes_[np.argmax(adjusted)]
    applicable = np.array([diagnostics[r["id"]]["status"] == "applicable" for r in rows])
    supported = np.array([applicable[i] and y[i] in diagnostics[r["id"]]["allowed"]
                          for i, r in enumerate(rows)])
    contradicted = applicable & ~supported
    proposal_conflict = np.array([applicable[i] and base[i] not in diagnostics[r["id"]]["allowed"]
                                  for i, r in enumerate(rows)])
    changed = applicable & (base != soft)
    eligible = np.flatnonzero(applicable)
    allowed_sets = [set(diagnostics[rows[i]["id"]]["allowed"]) for i in eligible]
    cases = [{"id": rows[i]["id"], "event_id": events[i], "historical": y[i],
              "base": base[i], "soft": soft[i], "allowed": diagnostics[rows[i]["id"]]["allowed"],
              "proposal_conflict": bool(proposal_conflict[i]),
              "historical_in_suggestion": bool(supported[i]),
              "unknown_conditions": diagnostics[rows[i]["id"]].get("unknown_conditions", []),
              "review_note": diagnostics[rows[i]["id"]].get("review_note", False)}
             for i in eligible]
    return {
        "baseline": {"all": evaluate(y, base, np.ones(len(rows), dtype=bool)),
                     "applicable": evaluate(y, base, applicable),
                     "supported": evaluate(y, base, supported)},
        "soft_x2": {"all": evaluate(y, soft, np.ones(len(rows), dtype=bool)),
                    "applicable": evaluate(y, soft, applicable),
                    "supported": evaluate(y, soft, supported),
                    "accuracy_delta_event_bootstrap": event_bootstrap_delta(
                        y, base, soft, eligible, events),
                    "shuffled_suggestion_control": shuffled_suggestion_control(
                        y, base, soft, probabilities, np.array(LABELS), eligible, allowed_sets)},
        "advisory_conflict": {"n": int(proposal_conflict.sum()),
                              "historical_type_rejected": int((proposal_conflict & contradicted).sum()),
                              "baseline_error_flagged": int((proposal_conflict & (base != y)).sum()),
                              "baseline_correct_flagged": int((proposal_conflict & (base == y)).sum()),
                              "accepted_n": int((applicable & ~proposal_conflict).sum()),
                              "accepted_accuracy": evaluate(y, base, applicable & ~proposal_conflict)["accuracy"]},
        "changes": {"n": int(changed.sum()), "helped": int((changed & (base != y) & (soft == y)).sum()),
                    "hurt": int((changed & (base == y) & (soft != y)).sum()),
                    "neither_correct": int((changed & (base != y) & (soft != y)).sum())},
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path,
                        default=ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    rows = read(args.package / "train.jsonl")
    y = np.array([label(r) for r in rows])
    refs, reference_audit = prepare_reference(rows)
    regions = resolve_regions(rows, ROOT / "lake/catalog/lake.db")
    lib = load()
    diagnostics = {}
    for row in rows:
        _, diagnostics[row["id"]] = rule_features(row, refs.get(row["id"]),
                                                   regions.get(row["id"]), lib)
    applicable = [d for d in diagnostics.values() if d["status"] == "applicable"]
    report = {"scope": "frozen_train_only; test40_never_opened", "model": "weighted_char_tfidf_LR_C3",
              "design": "out_of_fold; fixed_x2_advisory_only; no_hard_mask_or_tuning",
              "package": str(args.package), "reference_audit": dict(reference_audit),
              "m2": {"applicable_n": len(applicable),
                     "regional": dict(Counter(d["region"] for d in applicable)),
                     "suggestion_sizes": dict(Counter(len(d["allowed"]) for d in applicable)),
                     "unknown_conditions_n": sum(bool(d.get("unknown_conditions")) for d in applicable)},
              "axes": {axis: run_axis(rows, y, diagnostics, axis) for axis in ("event", "agency")}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"m2": report["m2"], "axes": {
        axis: {k: section[k] for k in ("baseline", "soft_x2", "advisory_conflict", "changes")}
        for axis, section in report["axes"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

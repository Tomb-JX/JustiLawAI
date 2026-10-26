"""Latent candidate-path training from field values, without invented edge gold.

Each record has NIL plus source-bound candidate paths. A positive field trains
the total probability of all evidence-local, value-compatible paths; a missing
field trains NIL with an explicit, varied weak-negative weight.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import same_value
from experiment_age_count_closure import evidence_contains
from experiment_candidate_nil import threshold_from_oof
from experiment_relation_suite import (AMOUNT_FIELDS, COUNT_FIELD, amount_features,
                                       count_features, count_paths, oof_partitions, split_records)
from experiment_silver_supervised_pipeline import measure, present
from minimal_amount_closure import event_ids, load_records


class BagSoftmax:
    def __init__(self) -> None:
        self.weights: dict[str, float] = defaultdict(float)

    def logit(self, x: dict[str, float]) -> float:
        return max(-20.0, min(20.0, sum(self.weights[k] * v for k, v in x.items())))

    def posterior(self, features: list[dict[str, float]]) -> list[float]:
        values = [math.exp(self.logit(x)) for x in features]
        denominator = 1.0 + sum(values)  # NIL has fixed logit zero.
        return [v / denominator for v in values]

    def fit(self, bags: list[tuple[list[dict[str, float]], set[int] | None]],
            missing_weight: float, epochs: int = 150, learning_rate: float = 0.9,
            l2: float = 0.0015) -> None:
        usable = [(xs, positives) for xs, positives in bags if xs and
                  (positives is None or positives)]
        if not usable:
            raise ValueError("no_usable_bags")
        for _ in range(epochs):
            gradient: dict[str, float] = defaultdict(float)
            total_weight = 0.0
            for xs, positives in usable:
                post = self.posterior(xs)
                selected_mass = sum(post[i] for i in positives) if positives is not None else 0.0
                weight = missing_weight if positives is None else 1.0
                if weight == 0:
                    continue
                total_weight += weight
                for i, x in enumerate(xs):
                    coefficient = post[i] - (post[i] / selected_mass if positives is not None and
                                             i in positives and selected_mass > 0 else 0.0)
                    for key, value in x.items():
                        gradient[key] += weight * coefficient * value
            if total_weight == 0:
                raise ValueError("no_weighted_bags")
            for key in set(self.weights) | set(gradient):
                self.weights[key] -= learning_rate * (
                    gradient[key] / total_weight + l2 * self.weights[key])


def paths_and_features(inp: dict, packet: dict, field: str) -> tuple[list[dict], list[dict[str, float]]]:
    if field == COUNT_FIELD:
        paths = count_paths(packet, inp["target"], inp.get("aliases") or ())
        return paths, [count_features(p, inp, packet, "local_relation") for p in paths]
    paths = [{"id": q["candidate_id"], "kind": "amount", "value": q["engine_projection"],
              "start": q["start"], "end": q["end"], "source_span_id": q["source_span_id"],
              "node": q} for q in packet["quantities"] if q["type"] == "amount"
             and q["parse_status"] == "resolved"]
    feature_fn = amount_features("local_relation")
    return paths, [feature_fn(p["node"], inp, packet) for p in paths]


def field_item(ref: dict, field: str) -> dict:
    group, name = field.split(".")
    return ref["reference_elements"][group][name]


def compatible(field: str, path: dict, item: dict) -> bool:
    if not present(item) or not evidence_contains(path, item):
        return False
    if field == COUNT_FIELD:
        return path["value"] == item["value"]
    return same_value(field, item["value"], path["node"])


def training_bags(records: list[tuple], field: str) -> tuple[list[tuple], dict]:
    bags = []
    stats = Counter()
    for _, inp, packet, ref in records:
        item = field_item(ref, field)
        paths, xs = paths_and_features(inp, packet, field)
        stats["records"] += 1
        if not present(item):
            stats["silver_missing"] += 1
            bags.append((xs, None))
            continue
        stats["silver_positive"] += 1
        indices = {i for i, p in enumerate(paths) if compatible(field, p, item)}
        if not indices:
            stats["positive_without_local_path"] += 1
            continue
        stats["positive_with_local_path"] += 1
        stats["multiple_compatible_paths"] += len(indices) > 1
        bags.append((xs, indices))
    return bags, dict(stats)


def predict_rows(records: list[tuple], field: str, model: BagSoftmax) -> list[dict]:
    out = []
    for rid, inp, packet, ref in records:
        paths, xs = paths_and_features(inp, packet, field)
        probabilities = model.posterior(xs)
        i = max(range(len(paths)), key=lambda j: (probabilities[j], -paths[j]["start"])) if paths else None
        chosen = paths[i] if i is not None else None
        item = field_item(ref, field)
        match = bool(chosen and present(item) and (chosen["value"] == item["value"]
                      if field == COUNT_FIELD else same_value(field, item["value"], chosen["node"])))
        out.append({"id": rid, "score": probabilities[i] if i is not None else 0.0,
                    "candidate_id": chosen["id"] if chosen else None,
                    "candidate_kind": chosen["kind"] if chosen else None,
                    "candidate_value": chosen["value"] if chosen else None,
                    "candidate_count": len(paths), "nil_probability": 1 - sum(probabilities),
                    "silver_positive": present(item), "silver_match_if_selected": match,
                    "evidence_local_if_match": bool(match and compatible(field, chosen, item))})
    return out


def run(teacher: Path, originals: Path, silver: Path) -> tuple[dict, list[dict]]:
    records = load_records(teacher, originals, silver, {"train", "valid"})
    train, valid = split_records(records)
    started = time.perf_counter()
    report = {"scope": "latent_paths_train_event_oof_valid_diagnostic", "test_labels_read": False,
              "edge_gold_used": False, "train_records": len(train), "valid_records": len(valid),
              "train_events": len(event_ids(train)), "valid_events": len(event_ids(valid)),
              "fields": {}, "input_sha256": {k: hashlib.sha256(p.read_bytes()).hexdigest()
                                           for k, p in {"teacher": teacher, "originals": originals,
                                                        "silver": silver}.items()}}
    predictions = []
    for field in (*AMOUNT_FIELDS, COUNT_FIELD):
        report["fields"][field] = {}
        for missing_weight in ((1.0,) if field != COUNT_FIELD else (0.25, 1.0)):
            name = str(missing_weight)
            oof = []
            for fit_rows, held in oof_partitions(train):
                bags, _ = training_bags(fit_rows, field)
                model = BagSoftmax()
                model.fit(bags, missing_weight)
                oof.extend(predict_rows(held, field, model))
            threshold, train_metric = threshold_from_oof(oof)
            bags, stats = training_bags(train, field)
            model = BagSoftmax()
            model.fit(bags, missing_weight)
            valid_rows = predict_rows(valid, field, model)
            valid_metric = measure(valid_rows, threshold)
            valid_metric["selected_evidence_local_match"] = sum(
                bool(r["candidate_id"] and r["score"] >= threshold and r["evidence_local_if_match"])
                for r in valid_rows)
            report["fields"][field][name] = {"training": stats, "missing_weight": missing_weight,
                                              "threshold": threshold, "train_oof": train_metric,
                                              "valid": valid_metric,
                                              "valid_risk_coverage": {str(t): measure(valid_rows, t)
                                                                      for t in (0.15, 0.3, 0.5, 0.7)}}
            predictions.extend({"field": field, "missing_weight": missing_weight,
                                "split": "valid", **r} for r in valid_rows)
    report["runtime_seconds"] = round(time.perf_counter() - started, 3)
    return report, predictions


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "report", "predictions"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    if args.report.exists() or args.predictions.exists():
        ap.error("output_already_exists")
    report, predictions = run(args.teacher, args.originals, args.silver)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    args.predictions.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in predictions), "utf-8")
    print(json.dumps({"runtime_seconds": report["runtime_seconds"],
                      "valid": {f: {k: v["valid"] for k, v in routes.items()}
                                for f, routes in report["fields"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

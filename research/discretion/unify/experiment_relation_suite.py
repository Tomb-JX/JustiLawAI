"""Same-candidate relation-feature ablations on event-split development data.

Silver values/evidence weakly constrain candidate paths. They do not label
person, event or field-role edges. No opened test labels are read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

from audit_supply_replay import same_value
from experiment_age_count_closure import age_prediction, count_candidates, evidence_contains
from experiment_candidate_nil import candidate_x, fit as fit_amount, predict_rows as amount_rows, threshold_from_oof
from experiment_participant_list import candidate_lists
from experiment_selective_binding import event_fold
from experiment_silver_supervised_pipeline import SparseLogistic, measure, present
from minimal_amount_closure import event_ids, load_records, scene_features

AMOUNT_FIELDS = ("amounts.personal_stake", "amounts.onsite_stake_total")
COUNT_FIELD = "persons.participant_count"
FEATURE_SETS = ("surface", "local_relation", "scene_relation")


def surface_only(x: dict[str, float]) -> dict[str, float]:
    return {k: v for k, v in x.items() if k.startswith(("L:", "R:", "context_"))}


def amount_features(config: str):
    def make(q: dict, inp: dict, packet: dict) -> dict[str, float]:
        if config == "surface":
            return surface_only(candidate_x(q, inp, packet))
        if config == "local_relation":
            return candidate_x(q, inp, packet)
        return scene_features(q, inp, packet, "scene_structure")
    return make


def count_paths(packet: dict, target: str, aliases: list[str] | tuple[str, ...]) -> list[dict]:
    out = [{"id": q["candidate_id"], "kind": "explicit", "value": q["engine_projection"]["min"],
            "start": q["start"], "end": q["end"], "source_span_id": q["source_span_id"],
            "node": q} for q in count_candidates(packet)]
    out.extend({"id": l["candidate_id"], "kind": "list", "value": l["value"],
                "start": l["list_start"], "end": l["list_end"],
                "source_span_id": l["source_span_id"], "node": l}
               for l in candidate_lists(packet, target, aliases))
    return out


def grams(value: str, prefix: str) -> dict[str, float]:
    keys = {prefix + value[i:i + n] for n in (1, 2, 3) for i in range(len(value) - n + 1)}
    scale = 1 / math.sqrt(max(1, len(keys)))
    return {key: scale for key in keys}


def count_features(path: dict, inp: dict, packet: dict, config: str) -> dict[str, float]:
    view = next(v for v in packet["visible_spans"] if v["span_id"] == path["source_span_id"])
    left = view["quote"][max(0, path["start"] - view["start"] - 28):path["start"] - view["start"]]
    right = view["quote"][path["end"] - view["start"]:
                          min(len(view["quote"]), path["end"] - view["start"] + 35)]
    for name in sorted({inp["target"], *(inp.get("aliases") or ())}, key=len, reverse=True):
        if name:
            left, right = left.replace(name, "〈目标〉"), right.replace(name, "〈目标〉")
    x = {**grams(left, "L:"), **grams(right, "R:")}
    if config == "surface":
        return x
    x["source:" + path["kind"]] = 1.0
    x["view_role:" + str(view.get("role") or "unknown")] = 1.0
    if path["kind"] == "explicit":
        q = path["node"]
        x["role:" + str(q.get("role_hint") or "untyped")] = 1.0
        x["actor:" + str(q.get("actor_status") or "unresolved")] = 1.0
        x["scene:" + str(next((s["kind"] for s in packet["scenes"]
                               if s["scene_id"] == q["scene_id"]), "unknown"))] = 1.0
    else:
        l = path["node"]
        x["predicate:" + l["trigger"]] = 1.0
        x["target_in_list"] = 1.0
        x["masked_collision:" + str(l["masked_surface_collision"])] = 1.0
        x["list_size:" + ("2-3" if l["value"] <= 3 else "4-6" if l["value"] <= 6 else "7+")] = 1.0
        x["trigger_distance:" + ("near" if l["trigger_start"] - l["list_end"] <= 24 else "far")] = 1.0
    if config == "scene_relation":
        x["candidate_count:" + str(min(5, len(count_paths(packet, inp["target"], inp.get("aliases") or ()))))] = 1.0
        x["document_target_mentions:" + str(min(5, len(packet["mentions"]))) ] = 1.0
    return x


def count_examples(records: list[tuple], config: str, missing_negative: bool) -> tuple[list[tuple], dict]:
    examples = []
    stats = Counter()
    for _, inp, packet, ref in records:
        item = ref["reference_elements"]["persons"]["participant_count"]
        paths = count_paths(packet, inp["target"], inp.get("aliases") or ())
        stats["records"] += 1
        if not present(item):
            stats["silver_missing_records"] += 1
            if missing_negative:
                for p in paths:
                    examples.append((count_features(p, inp, packet, config), False))
                    stats["missing_negative_paths"] += 1
            continue
        matches = [p for p in paths if p["value"] == item["value"] and evidence_contains(p, item)]
        if not matches:
            stats["positive_without_local_path"] += 1
            continue
        stats["positive_compatible_records"] += 1
        stats["ambiguous_compatible_records"] += len(matches) > 1
        for p in matches:
            examples.append((count_features(p, inp, packet, config), True))
            stats["compatible_positive_paths"] += 1
        for p in paths:
            if p["value"] != item["value"]:
                examples.append((count_features(p, inp, packet, config), False))
                stats["different_value_negative_paths"] += 1
    return examples, dict(stats)


def fit_count(records: list[tuple], config: str, missing_negative: bool) -> tuple[SparseLogistic, dict]:
    examples, stats = count_examples(records, config, missing_negative)
    positives = [x for x, y in examples if y]
    negatives = [x for x, y in examples if not y]
    if not positives or not negatives:
        raise ValueError("count_model_class_missing")
    repeats = max(1, round(len(negatives) / len(positives)))
    model = SparseLogistic()
    model.fit(examples + [(x, True) for _ in range(repeats - 1) for x in positives])
    stats["positive_repeat_factor"] = repeats
    return model, stats


def count_scored(records: list[tuple], model: SparseLogistic, config: str) -> list[dict]:
    result = []
    for rid, inp, packet, ref in records:
        paths = count_paths(packet, inp["target"], inp.get("aliases") or ())
        ranked = sorted(paths, key=lambda p: (-model.predict(count_features(p, inp, packet, config)),
                                              p["start"], p["id"]))
        chosen = ranked[0] if ranked else None
        item = ref["reference_elements"]["persons"]["participant_count"]
        result.append({"id": rid, "score": model.predict(count_features(chosen, inp, packet, config))
                       if chosen else 0.0, "candidate_id": chosen["id"] if chosen else None,
                       "candidate_kind": chosen["kind"] if chosen else None,
                       "candidate_value": chosen["value"] if chosen else None,
                       "candidate_count": len(paths), "silver_positive": present(item),
                       "silver_match_if_selected": bool(chosen and present(item) and
                                                        chosen["value"] == item["value"]),
                       "evidence_local_if_match": bool(chosen and present(item) and
                                                       chosen["value"] == item["value"] and
                                                       evidence_contains(chosen, item))})
    return result


def split_records(records: list[tuple]) -> tuple[list[tuple], list[tuple]]:
    train = [r for r in records if r[3]["metadata"]["split"] == "train"]
    valid = [r for r in records if r[3]["metadata"]["split"] == "valid"]
    if event_ids(train) & event_ids(valid):
        raise ValueError("train_valid_event_overlap")
    return train, valid


def oof_partitions(train: list[tuple]):
    for fold in range(5):
        fit_rows = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) != fold]
        held = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) == fold]
        yield fit_rows, held


def evaluate_rows(rows: list[dict], threshold: float) -> dict:
    metric = measure(rows, threshold)
    metric["selected_evidence_local_match"] = sum(
        r.get("evidence_local_if_match", False) and r["candidate_id"] is not None
        and r["score"] >= threshold for r in rows)
    return metric


def annotate_amount_locality(rows: list[dict], records: list[tuple], field: str) -> list[dict]:
    refs = {rid: (packet, ref) for rid, _, packet, ref in records}
    for row in rows:
        packet, ref = refs[row["id"]]
        item = ref["reference_elements"]["amounts"][field.split(".")[1]]
        q = next((q for q in packet["quantities"] if q["candidate_id"] == row["candidate_id"]), None)
        row["evidence_local_if_match"] = bool(row["silver_match_if_selected"] and q and
                                                evidence_contains(q, item))
    return rows


def compare(teacher: Path, originals: Path, silver: Path) -> tuple[dict, list[dict]]:
    records = load_records(teacher, originals, silver, {"train", "valid"})
    train, valid = split_records(records)
    started = time.perf_counter()
    report = {"scope": "train_event_oof_valid_diagnostic", "test_labels_read": False,
              "silver_edge_gold": False, "train_records": len(train), "valid_records": len(valid),
              "train_events": len(event_ids(train)), "valid_events": len(event_ids(valid)),
              "input_sha256": {k: hashlib.sha256(p.read_bytes()).hexdigest()
                               for k, p in {"teacher": teacher, "originals": originals,
                                            "silver": silver}.items()},
              "amounts": {}, "count": {}, "age": {}}
    predictions = []
    for field in AMOUNT_FIELDS:
        by_config = {}
        for config in FEATURE_SETS:
            fn = amount_features(config)
            oof = []
            for fit_rows, held in oof_partitions(train):
                model, _ = fit_amount(fit_rows, field, fn)
                oof.extend(amount_rows(held, field, model, fn))
            threshold, train_metric = threshold_from_oof(oof)
            model, stats = fit_amount(train, field, fn)
            valid_rows = annotate_amount_locality(amount_rows(valid, field, model, fn), valid, field)
            by_config[config] = {"threshold": threshold, "training": stats,
                                 "train_oof": train_metric,
                                 "valid": evaluate_rows(valid_rows, threshold),
                                 "valid_risk_coverage": {str(t): evaluate_rows(valid_rows, t)
                                                         for t in (0.35, 0.5, 0.65, 0.8)}}
            predictions.extend({"field": field, "config": config, "split": "valid", **r}
                               for r in valid_rows)
        report["amounts"][field] = by_config
    for missing_negative in (False, True):
        policy = "different_value_only" if not missing_negative else "plus_silver_missing"
        report["count"][policy] = {}
        for config in FEATURE_SETS:
            oof = []
            for fit_rows, held in oof_partitions(train):
                try:
                    model, _ = fit_count(fit_rows, config, missing_negative)
                except ValueError as exc:
                    report["count"][policy][config] = {"unavailable": str(exc)}
                    break
                oof.extend(count_scored(held, model, config))
            else:
                threshold, train_metric = threshold_from_oof(oof)
                model, stats = fit_count(train, config, missing_negative)
                valid_rows = count_scored(valid, model, config)
                report["count"][policy][config] = {
                    "threshold": threshold, "training": stats, "train_oof": train_metric,
                    "valid": evaluate_rows(valid_rows, threshold),
                    "valid_risk_coverage": {str(t): evaluate_rows(valid_rows, t)
                                            for t in (0.35, 0.5, 0.65, 0.8)},
                    "valid_selected_by_source": dict(Counter(
                        r["candidate_kind"] for r in valid_rows if r["candidate_id"] is not None
                        and r["score"] >= threshold))}
                predictions.extend({"field": COUNT_FIELD, "config": config, "policy": policy,
                                    "split": "valid", **r} for r in valid_rows)
    for split, source in (("train", train), ("valid", valid)):
        stats = Counter()
        for _, _, packet, ref in source:
            item = ref["reference_elements"]["person"]["age"]
            pred = age_prediction(packet)
            stats["silver_positive"] += present(item)
            stats["selected"] += pred["status"] == "selected"
            stats["matched_silver"] += pred["status"] == "selected" and present(item) and pred["value"] == item["value"]
            stats["output_on_silver_missing"] += pred["status"] == "selected" and not present(item)
        report["age"][split] = dict(stats)
    report["runtime_seconds"] = round(time.perf_counter() - started, 3)
    return report, predictions


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "report", "predictions"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    if args.report.exists() or args.predictions.exists():
        ap.error("output_already_exists")
    report, predictions = compare(args.teacher, args.originals, args.silver)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    args.predictions.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in predictions), "utf-8")
    print(json.dumps({"runtime_seconds": report["runtime_seconds"],
                      "amount_valid": {f: {k: d["valid"] for k, d in configs.items()}
                                       for f, configs in report["amounts"].items()},
                      "count_valid": {policy: {k: d.get("valid", d) for k, d in configs.items()}
                                      for policy, configs in report["count"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

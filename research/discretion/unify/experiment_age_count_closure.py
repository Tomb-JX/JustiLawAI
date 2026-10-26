"""Frozen age derivation and participant-count candidate/NIL experiment.

Fit only sees train/valid. Test verifies a frozen artifact; infer needs no silver.
Every selected value carries source candidate/operand coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

from audit_supply_replay import rows, same_value
from experiment_age_derivation import birth_interval, completed_age
from experiment_candidate_nil import candidate_x, threshold_from_oof
from experiment_selective_binding import event_fold
from experiment_silver_supervised_pipeline import SparseLogistic, measure, present
from minimal_amount_closure import event_ids, load_records
from supply_packet import build_packet

COUNT_FIELD = "persons.participant_count"
AGE_FIELD = "person.age"


def file_hashes(teacher: Path, originals: Path, silver: Path | None = None) -> dict:
    paths = {"teacher": teacher, "originals": originals}
    if silver is not None:
        paths["silver"] = silver
    return {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}


def count_candidates(packet: dict) -> list[dict]:
    return [q for q in packet["quantities"] if q["type"] == "count" and
            q["parse_status"] == "resolved" and q.get("unit") == "人" and
            (q.get("engine_projection") or {}).get("exact") is True]


def count_features(q: dict, inp: dict, packet: dict) -> dict[str, float]:
    x = candidate_x(q, inp, packet)
    same_scene = [a for a in count_candidates(packet) if a["scene_id"] == q["scene_id"]]
    x["scene_person_count:" + str(min(len(same_scene), 4))] = 1.0
    x["candidate_count:" + str(min(len(count_candidates(packet)), 4))] = 1.0
    return x


def evidence_contains(q: dict, item: dict) -> bool:
    return any(type(e.get("start")) is int and type(e.get("end")) is int and
               e["start"] <= q["start"] < q["end"] <= e["end"]
               for e in item.get("evidence") or [])


def training_examples(records: list[tuple]) -> tuple[list[tuple], dict]:
    out = []
    stats = Counter()
    for _, inp, packet, ref in records:
        item = ref["reference_elements"]["persons"]["participant_count"]
        qs = count_candidates(packet)
        stats["records"] += 1
        if not present(item):
            for q in qs:
                out.append((count_features(q, inp, packet), False))
                stats["negative_from_silver_missing"] += 1
            continue
        stats["silver_positive"] += 1
        matches = [q for q in qs if same_value(COUNT_FIELD, item["value"], q)
                   and evidence_contains(q, item)]
        if len(matches) != 1:
            stats["positive_missing_or_ambiguous"] += 1
            continue
        positive = matches[0]
        out.append((count_features(positive, inp, packet), True))
        stats["positive_candidates"] += 1
        for q in qs:
            if q["candidate_id"] != positive["candidate_id"] and not same_value(
                    COUNT_FIELD, item["value"], q):
                out.append((count_features(q, inp, packet), False))
                stats["different_value_negatives"] += 1
    return out, dict(stats)


def fit_count(records: list[tuple]) -> tuple[SparseLogistic, dict]:
    examples, stats = training_examples(records)
    positives = [x for x, y in examples if y]
    negatives = [x for x, y in examples if not y]
    if not positives or not negatives:
        raise ValueError("count_training_class_missing")
    repeats = max(1, round(len(negatives) / len(positives)))
    balanced = examples + [(x, True) for _ in range(repeats - 1) for x in positives]
    model = SparseLogistic()
    model.fit(balanced)
    stats["positive_repeat_factor"] = repeats
    return model, stats


def count_prediction(inp: dict, packet: dict, model: SparseLogistic, threshold: float) -> dict:
    qs = count_candidates(packet)
    ranked = sorted(qs, key=lambda q: (-model.predict(count_features(q, inp, packet)), q["start"]))
    if not ranked:
        return {"status": "abstain", "reason": "no_exact_person_count_candidate", "candidate_count": 0}
    q = ranked[0]
    score = model.predict(count_features(q, inp, packet))
    if score < threshold:
        return {"status": "abstain", "reason": "below_frozen_nil_threshold", "score": score,
                "candidate_count": len(qs), "threshold": threshold}
    return {"status": "selected", "route": "count_candidate_nil", "value": q["engine_projection"]["min"],
            "candidate_id": q["candidate_id"], "raw": q["raw"], "start": q["start"],
            "end": q["end"], "source_span_id": q["source_span_id"], "score": score,
            "threshold": threshold, "candidate_count": len(qs)}


def count_rows(records: list[tuple], model: SparseLogistic) -> list[dict]:
    out = []
    for rid, inp, packet, ref in records:
        item = ref["reference_elements"]["persons"]["participant_count"]
        p = count_prediction(inp, packet, model, 0.0)
        out.append({"id": rid, "candidate_id": p.get("candidate_id"), "score": p.get("score", 0.0),
                    "silver_positive": present(item), "silver_match_if_selected": bool(
                        p["status"] == "selected" and present(item) and p["value"] == item["value"])})
    return out


def age_prediction(packet: dict) -> dict:
    views = {v["span_id"]: v for v in packet["visible_spans"]}
    births = [q for q in packet["quantities"] if birth_interval(q) is not None]
    events = [q for q in packet["quantities"] if q["type"] == "date" and
              q.get("parse_status") == "resolved" and q.get("role_hint") not in
              {"birth", "prior_penalty"} and (q.get("engine_projection") or {}).get("date") and
              views[q["source_span_id"]]["zone"] == "facts"]
    alternatives = []
    for b in births:
        first, last = birth_interval(b)
        for e in events:
            event = date.fromisoformat(e["engine_projection"]["date"])
            lo, hi = completed_age(last, event), completed_age(first, event)
            if 0 <= lo <= hi <= 130:
                alternatives.append((lo, hi, b, e))
    possible = {age for lo, hi, _, _ in alternatives for age in range(lo, hi + 1)}
    if len(possible) != 1:
        return {"status": "abstain", "reason": "no_operands" if not alternatives else
                "ambiguous_age_or_event", "birth_candidates": len(births),
                "event_candidates": len(events), "possible_age_count": len(possible)}
    _, _, b, e = alternatives[0]
    return {"status": "selected", "route": "date_interval_derivation", "value": next(iter(possible)),
            "birth_operand": {k: b[k] for k in ("candidate_id", "raw", "start", "end", "source_span_id")},
            "event_operand": {k: e[k] for k in ("candidate_id", "raw", "start", "end", "source_span_id")},
            "consistent_operand_pairs": len(alternatives)}


def score_age(records: list[tuple]) -> dict:
    rows_out = []
    for rid, _, packet, ref in records:
        item = ref["reference_elements"]["person"]["age"]
        p = age_prediction(packet)
        rows_out.append({"id": rid, "candidate_id": "derived" if p["status"] == "selected" else None,
                         "score": 1.0, "silver_positive": present(item),
                         "silver_match_if_selected": bool(p["status"] == "selected" and
                                                          present(item) and p["value"] == item["value"])})
    return measure(rows_out, 0.5)


def fit(teacher: Path, originals: Path, silver: Path) -> tuple[dict, dict]:
    records = load_records(teacher, originals, silver, {"train", "valid"})
    train = [r for r in records if r[3]["metadata"]["split"] == "train"]
    valid = [r for r in records if r[3]["metadata"]["split"] == "valid"]
    if event_ids(train) & event_ids(valid):
        raise ValueError("train_valid_event_overlap")
    oof = []
    for fold in range(5):
        fit_rows = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) != fold]
        held = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) == fold]
        model, _ = fit_count(fit_rows)
        oof.extend(count_rows(held, model))
    threshold, train_oof = threshold_from_oof(oof)
    model, stats = fit_count(train)
    artifact = {"version": "age-count-closure-1", "count": {"threshold": threshold,
                "weights": dict(model.weights), "bias": model.bias},
                "age": {"route": "date_interval_derivation"},
                "input_sha256": file_hashes(teacher, originals, silver),
                "development_event_hashes": sorted(hashlib.sha256(e.encode()).hexdigest()
                                                   for e in event_ids(train) | event_ids(valid)),
                "test_labels_used_for_fit": False}
    report = {"scope": "train_valid", "train_records": len(train), "valid_records": len(valid),
              "count": {"training": stats, "threshold": threshold, "train_oof": train_oof,
                        "valid": measure(count_rows(valid, model), threshold)},
              "age": {"train": score_age(train), "valid": score_age(valid)}}
    return artifact, report


def predict_record(rid: str, inp: dict, packet: dict, artifact: dict) -> dict:
    model = SparseLogistic()
    model.weights.update(artifact["count"]["weights"])
    model.bias = artifact["count"]["bias"]
    return {"id": rid, "source_sha256": inp["source_sha256"], "target": inp["target"],
            "fields": {COUNT_FIELD: count_prediction(inp, packet, model, artifact["count"]["threshold"]),
                       AGE_FIELD: age_prediction(packet)}}


def score_predictions(predictions: list[dict], records: list[tuple]) -> dict:
    refs = {rid: ref for rid, _, _, ref in records}
    result = {}
    for field, group, name in ((COUNT_FIELD, "persons", "participant_count"), (AGE_FIELD, "person", "age")):
        entries = []
        for row in predictions:
            p = row["fields"][field]
            item = refs[row["id"]]["reference_elements"][group][name]
            entries.append({"id": row["id"], "score": 1.0,
                            "candidate_id": p.get("candidate_id", "derived") if p["status"] == "selected" else None,
                            "silver_positive": present(item), "silver_match_if_selected": bool(
                                p["status"] == "selected" and present(item) and p["value"] == item["value"])})
        result[field] = measure(entries, 0.5)
    return result


def source_records(teacher: Path, originals: Path) -> list[tuple]:
    origins = {r["id"]: r["text_full"] for r in rows(originals)}
    out = []
    for inp in rows(teacher):
        rid = inp["id"]
        text = origins[rid]
        if hashlib.sha256(text.encode()).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch:" + rid)
        out.append((rid, inp, build_packet(text, inp, record_id=rid)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="stage", required=True)
    for stage in ("fit", "test", "infer"):
        p = sub.add_parser(stage)
        for name in (("teacher", "originals", "silver", "artifact", "report") if stage == "fit" else
                     ("teacher", "originals", "silver", "artifact", "predictions", "report") if stage == "test" else
                     ("teacher", "originals", "artifact", "predictions")):
            p.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    if args.stage == "fit":
        artifact, report = fit(args.teacher, args.originals, args.silver)
        outputs = {args.artifact: artifact, args.report: report}
    else:
        artifact = json.loads(args.artifact.read_text("utf-8"))
        expected = artifact["input_sha256"]
        observed = file_hashes(args.teacher, args.originals, args.silver if args.stage == "test" else None)
        if any(observed[k] != expected[k] for k in observed):
            raise ValueError("frozen_input_hash_mismatch")
        if args.stage == "test":
            records = load_records(args.teacher, args.originals, args.silver, {"test"})
            if len(records) != 40 or set(artifact["development_event_hashes"]) & {
                    hashlib.sha256(e.encode()).hexdigest() for e in event_ids(records)}:
                raise ValueError("test_scope_or_event_overlap")
            predictions = [predict_record(rid, inp, packet, artifact) for rid, inp, packet, _ in records]
            report = {"scope": "frozen_test_once", "records": len(records),
                      "metrics": score_predictions(predictions, records)}
            outputs = {args.predictions: predictions, args.report: report}
        else:
            predictions = [predict_record(rid, inp, packet, artifact)
                           for rid, inp, packet in source_records(args.teacher, args.originals)]
            outputs = {args.predictions: predictions}
    for path, data in outputs.items():
        if path.exists():
            ap.error("output_already_exists:" + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, list):
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in data), "utf-8")
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    summary = {"stage": args.stage,
               "records": len(predictions) if args.stage != "fit" else
               report["train_records"] + report["valid_records"]}
    if args.stage != "infer":
        summary["metrics"] = report.get("metrics", report)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

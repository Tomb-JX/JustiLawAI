"""Freeze and evaluate a two-field amount binding pipeline.

`fit` uses train labels and valid for model-family selection. It writes a frozen
artifact before `test` may read the sealed test labels. `test` never refits or
retunes; it emits source-grounded predictions and a final evaluation report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows, same_value
from experiment_candidate_nil import candidate_x, fit as fit_candidate, predict_rows, threshold_from_oof
from experiment_selective_binding import event_fold
from experiment_silver_supervised_pipeline import SparseLogistic, measure, original_s2, present
from experiment_weak_role_model import FIELDS
from supply_packet import build_packet

CONFIGS = ("local", "scene_structure", "scene_text")


def scene_features(q: dict, inp: dict, packet: dict, config: str) -> dict[str, float]:
    x = candidate_x(q, inp, packet)
    if config == "local":
        return x
    scene = next((s for s in packet["scenes"] if s["scene_id"] == q["scene_id"]), None)
    if scene is None:
        return x
    same_scene = [a for a in packet["quantities"] if a["type"] == "amount" and
                  a["parse_status"] == "resolved" and a["scene_id"] == q["scene_id"]]
    n = len(same_scene)
    x["scene_amount_bucket:" + ("1" if n == 1 else "2-3" if n <= 3 else "4+")] = 1.0
    x["scene_span_bucket:" + ("short" if scene["end"] - scene["start"] < 80 else
                               "medium" if scene["end"] - scene["start"] < 180 else "long")] = 1.0
    pos = 0 if not same_scene else sorted(a["start"] for a in same_scene).index(q["start"])
    x["scene_amount_position:" + ("first" if pos == 0 else "last" if pos == n - 1 else "middle")] = 1.0
    mentions = [m for m in packet["mentions"] if scene["start"] <= m["start"] < m["end"] <= scene["end"]]
    x["scene_target_mention_bucket:" + ("0" if not mentions else "1" if len(mentions) == 1 else "2+")] = 1.0
    if config == "scene_text":
        view = next((v for v in packet["visible_spans"] if v["start"] <= scene["start"] and
                     scene["end"] <= v["end"]), None)
        if view is not None:
            clause = view["quote"][scene["start"] - view["start"]:scene["end"] - view["start"]]
            grams = {"SC:" + clause[i:i + ngram] for ngram in (2, 3)
                     for i in range(len(clause) - ngram + 1)}
            scale = 1 / math.sqrt(max(1, len(grams)))
            x.update({g: scale for g in grams})
    return x


def feature_fn(config: str):
    if config not in CONFIGS:
        raise ValueError("unknown_feature_config")
    return lambda q, inp, packet: scene_features(q, inp, packet, config)


def load_records(teacher_path: Path, originals_path: Path, silver_path: Path,
                 splits: set[str]) -> list[tuple]:
    refs = {r["id"]: r for r in rows(silver_path) if r.get("metadata", {}).get("split") in splits}
    origins = {r["id"]: r["text_full"] for r in rows(originals_path)}
    records = []
    for inp in rows(teacher_path):
        rid = inp["id"]
        if rid not in refs:
            continue
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch:" + rid)
        records.append((rid, inp, build_packet(text, inp, record_id=rid), refs[rid]))
    if {r[0] for r in records} != set(refs):
        raise ValueError("scope_mismatch")
    return records


def event_ids(records: list[tuple]) -> set[str]:
    return {r[3]["metadata"].get("event_id") or r[0] for r in records}


def hash_inputs(teacher_path: Path, originals_path: Path, silver_path: Path, engine_root: Path) -> dict:
    return {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
            "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
            "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
            "original_s2_binding_py": hashlib.sha256(
                (engine_root / "app/discretion/binding.py").read_bytes()).hexdigest()}


def bind_import(engine_root: Path):
    if not (engine_root / "app/discretion/binding.py").is_file():
        raise ValueError("engine_binding_missing")
    sys.path.insert(0, str(engine_root.resolve()))
    from app.discretion.binding import bind
    return bind


def compare_key(metric: dict, *, original: bool) -> tuple:
    # S2 wins exact ties; chosen family is frozen before test.
    return (metric["f1"], -metric["fp"], int(original))


def fit_dev(teacher_path: Path, originals_path: Path, silver_path: Path,
            engine_root: Path) -> tuple[dict, dict]:
    bind = bind_import(engine_root)
    records = load_records(teacher_path, originals_path, silver_path, {"train", "valid"})
    train = [r for r in records if r[3]["metadata"]["split"] == "train"]
    valid = [r for r in records if r[3]["metadata"]["split"] == "valid"]
    if event_ids(train) & event_ids(valid):
        raise ValueError("train_valid_event_overlap")
    artifact = {"version": "minimal-amount-closure-1", "fields": {},
                "reference_policy": "silver_high_confidence", "test_labels_used_for_fit": False,
                "development_event_hashes": sorted(hashlib.sha256(e.encode("utf-8")).hexdigest()
                                                   for e in event_ids(train) | event_ids(valid)),
                "input_sha256": hash_inputs(teacher_path, originals_path, silver_path, engine_root)}
    report = {"scope": "train_valid_model_selection", "test_labels_used": False,
              "train_records": len(train), "valid_records": len(valid),
              "train_events": len(event_ids(train)), "valid_events": len(event_ids(valid)), "fields": {}}
    for field in FIELDS:
        alternatives = {}
        old_valid = original_s2(valid, field, bind)
        old_train = original_s2(train, field, bind)
        for config in CONFIGS:
            fn = feature_fn(config)
            oof = []
            for fold in range(5):
                fit_rows = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) != fold]
                held = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) == fold]
                model, _ = fit_candidate(fit_rows, field, fn)
                oof.extend(predict_rows(held, field, model, fn))
            threshold, train_metric = threshold_from_oof(oof)
            model, stats = fit_candidate(train, field, fn)
            valid_rows = predict_rows(valid, field, model, fn)
            alternatives[config] = {"threshold": threshold, "train_oof": train_metric,
                                    "valid": measure(valid_rows, threshold),
                                    "training_stats": stats,
                                    "weights": dict(model.weights), "bias": model.bias,
                                    "valid_predictions": valid_rows}
        choices = [(old_valid, "original_s2", True)] + [
            (data["valid"], config, False) for config, data in alternatives.items()]
        chosen_metric, chosen, _ = max(choices, key=lambda x: compare_key(x[0], original=x[2]))
        artifact["fields"][field] = ({"route": "original_s2"} if chosen == "original_s2" else
                                      {"route": "candidate_nil", "config": chosen,
                                       "threshold": alternatives[chosen]["threshold"],
                                       "weights": alternatives[chosen]["weights"],
                                       "bias": alternatives[chosen]["bias"]})
        report["fields"][field] = {"selected_route": artifact["fields"][field]["route"],
                                   "selected_config": chosen,
                                   "selection_metric": chosen_metric,
                                   "original_s2": {"train": old_train, "valid": old_valid},
                                   "candidates": {config: {k: v for k, v in data.items()
                                                           if k not in {"weights", "bias", "valid_predictions"}}
                                                  for config, data in alternatives.items()},
                                   "valid_predictions": {config: data["valid_predictions"]
                                                         for config, data in alternatives.items()}}
    return artifact, report


def predict_candidate(rid: str, inp: dict, packet: dict, field: str, spec: dict) -> dict:
    model = SparseLogistic()
    model.weights.update(spec["weights"])
    model.bias = spec["bias"]
    fn = feature_fn(spec["config"])
    amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
    ranked = sorted(amounts, key=lambda q: (-model.predict(fn(q, inp, packet)), q["start"]))
    if not ranked:
        return {"status": "abstain", "reason": "no_amount_candidate", "score": None,
                "candidate_count": 0}
    selected = ranked[0]
    score = model.predict(fn(selected, inp, packet))
    if score < spec["threshold"]:
        return {"status": "abstain", "reason": "below_frozen_nil_threshold", "score": score,
                "candidate_count": len(amounts), "threshold": spec["threshold"]}
    return {"status": "selected", "reason": "candidate_exceeds_frozen_nil_threshold",
            "score": score, "threshold": spec["threshold"], "candidate_count": len(amounts),
            "candidate_id": selected["candidate_id"], "value": selected["engine_projection"],
            "raw": selected["raw"], "start": selected["start"], "end": selected["end"],
            "source_span_id": selected["source_span_id"]}


def predict_s2(inp: dict, field: str, bind) -> dict:
    result = bind(inp["sentence_view"], inp["target"], inp.get("aliases") or ())
    binding = result.bindings.get(field)
    if binding is None:
        return {"status": "abstain", "reason": "original_s2_abstain", "score": None}
    candidate = next((c for c in result.candidates if c.id == binding.candidate_id), None)
    view = next((v for v in inp["sentence_view"] if candidate and v.get("id") == candidate.sentence_id), None)
    return {"status": "selected", "reason": "original_s2_binding", "score": binding.confidence,
            "candidate_id": binding.candidate_id, "value": binding.value,
            "raw": candidate.text if candidate else None,
            "start": view["start"] + candidate.start if view else None,
            "end": view["start"] + candidate.end if view else None,
            "source_span_id": view.get("id") if view else None}


def predict_record(rid: str, inp: dict, packet: dict, artifact: dict, bind) -> dict:
    fields = {}
    for field, spec in artifact["fields"].items():
        output = (predict_s2(inp, field, bind) if spec["route"] == "original_s2" else
                  predict_candidate(rid, inp, packet, field, spec))
        output["route"] = spec["route"]
        fields[field] = output
    return {"id": rid, "source_sha256": inp["source_sha256"],
            "target": inp["target"], "fields": fields}


def score_final(predictions: list[dict], records: list[tuple]) -> dict:
    refs = {r[0]: r[3] for r in records}
    totals = {}
    for field in FIELDS:
        scored = []
        for row in predictions:
            output = row["fields"][field]
            item = refs[row["id"]]["reference_elements"]["amounts"][field.split(".")[1]]
            selected = output["status"] == "selected"
            scored.append({"id": row["id"], "score": 1.0,
                           "candidate_id": output.get("candidate_id") if selected else None,
                           "silver_positive": present(item),
                           "silver_match_if_selected": bool(selected and present(item) and same_value(
                               field, item["value"], {"engine_projection": output.get("value")}))})
        totals[field] = measure(scored, 0.5)
    return totals


def test_frozen(artifact: dict, teacher_path: Path, originals_path: Path,
                silver_path: Path, engine_root: Path) -> tuple[list[dict], dict]:
    bind = bind_import(engine_root)
    if artifact["input_sha256"] != hash_inputs(teacher_path, originals_path, silver_path, engine_root):
        raise ValueError("frozen_input_hash_mismatch")
    test = load_records(teacher_path, originals_path, silver_path, {"test"})
    if len(test) != 40:
        raise ValueError("unexpected_test_size")
    if set(artifact["development_event_hashes"]) & {
            hashlib.sha256(e.encode("utf-8")).hexdigest() for e in event_ids(test)}:
        raise ValueError("test_event_overlap")
    predictions = [predict_record(rid, inp, packet, artifact, bind) for rid, inp, packet, _ in test]
    report = {"scope": "frozen_test_once", "test_records": len(test),
              "test_events": len(event_ids(test)), "selected_routes": {
                  field: spec["route"] + (":" + spec["config"] if "config" in spec else "")
                  for field, spec in artifact["fields"].items()},
              "metrics": score_final(predictions, test),
              "original_s2": {field: original_s2(test, field, bind) for field in FIELDS},
              "input_sha256": artifact["input_sha256"]}
    return predictions, report


def infer_unlabeled(artifact: dict, teacher_path: Path, originals_path: Path,
                    engine_root: Path) -> list[dict]:
    bind = bind_import(engine_root)
    expected = artifact["input_sha256"]
    observed = {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                "original_s2_binding_py": hashlib.sha256(
                    (engine_root / "app/discretion/binding.py").read_bytes()).hexdigest()}
    if any(observed[key] != expected[key] for key in observed):
        raise ValueError("frozen_inference_input_hash_mismatch")
    origins = {r["id"]: r["text_full"] for r in rows(originals_path)}
    predictions = []
    for inp in rows(teacher_path):
        rid = inp["id"]
        if rid not in origins:
            raise ValueError("original_missing:" + rid)
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch:" + rid)
        packet = build_packet(text, inp, record_id=rid)
        predictions.append(predict_record(rid, inp, packet, artifact, bind))
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    for stage in ("fit", "test", "infer"):
        p = sub.add_parser(stage)
        inputs = ("teacher", "originals", "engine_root") if stage == "infer" else (
            "teacher", "originals", "silver", "engine_root")
        for name in inputs:
            p.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
        if stage == "fit":
            p.add_argument("--artifact", type=Path, required=True)
            p.add_argument("--report", type=Path, required=True)
        elif stage == "test":
            p.add_argument("--artifact", type=Path, required=True)
            p.add_argument("--predictions", type=Path, required=True)
            p.add_argument("--report", type=Path, required=True)
        else:
            p.add_argument("--artifact", type=Path, required=True)
            p.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "fit":
        if args.artifact.exists() or args.report.exists():
            parser.error("fit_output_already_exists")
        artifact, report = fit_dev(args.teacher, args.originals, args.silver, args.engine_root)
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", "utf-8")
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(json.dumps({f: {"selected": x["selected_config"],
                              "valid": x["selection_metric"]} for f, x in report["fields"].items()},
                         ensure_ascii=False))
    elif args.stage == "test":
        if args.predictions.exists() or args.report.exists():
            parser.error("test_output_already_exists")
        artifact = json.loads(args.artifact.read_text("utf-8"))
        predictions, report = test_frozen(artifact, args.teacher, args.originals, args.silver, args.engine_root)
        args.predictions.parent.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.predictions.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in predictions), "utf-8")
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(json.dumps(report, ensure_ascii=False))
    else:
        if args.predictions.exists():
            parser.error("inference_output_already_exists")
        artifact = json.loads(args.artifact.read_text("utf-8"))
        predictions = infer_unlabeled(artifact, args.teacher, args.originals, args.engine_root)
        args.predictions.parent.mkdir(parents=True, exist_ok=True)
        args.predictions.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in predictions), "utf-8")
        print(json.dumps({"unlabeled_predictions": len(predictions),
                          "selected_by_field": {field: sum(r["fields"][field]["status"] == "selected"
                                                    for r in predictions) for field in FIELDS}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

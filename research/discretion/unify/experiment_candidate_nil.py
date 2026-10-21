"""Silver-supervised candidate-vs-NIL amount binding.

For each field, evidence-local silver amounts are positive candidate labels;
amounts from silver-missing records and distinct-value rivals are negatives.
The maximum candidate score competes with a train-OOF NIL threshold.
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
from experiment_pairwise_binding_ranker import candidate_features
from experiment_selective_binding import event_fold
from experiment_silver_supervised_pipeline import SparseLogistic, measure, original_s2, present
from experiment_weak_role_model import FIELDS
from supply_packet import build_packet


def candidate_x(q: dict, inp: dict, packet: dict) -> dict[str, float]:
    lexical = candidate_features(q, packet, inp["target"], inp.get("aliases") or [])
    x = {key: 1 / math.sqrt(max(1, len(lexical))) for key in lexical}
    role = q.get("role_hint") or "untyped"
    actor = q.get("actor_status") or "unresolved"
    x["role:" + role] = 1.0
    x["actor:" + actor] = 1.0
    x["role_actor:" + role + ":" + actor] = 1.0
    scene = next((s for s in packet["scenes"] if s["scene_id"] == q["scene_id"]), None)
    x["scene:" + (scene["kind"] if scene else "unknown")] = 1.0
    return x


def candidate_examples(records: list[tuple], field: str) -> tuple[list[tuple], dict]:
    examples = []
    stats = Counter()
    for rid, inp, packet, ref in records:
        item = ref["reference_elements"]["amounts"][field.split(".")[1]]
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        if not present(item):
            for q in amounts:
                examples.append((candidate_x(q, inp, packet), False))
                stats["silver_missing_negative_candidates"] += 1
            continue
        matches = [q for q in amounts if same_value(field, item["value"], q)
                   and any(type(e.get("start")) is int and type(e.get("end")) is int
                           and e["start"] <= q["start"] < q["end"] <= e["end"]
                           for e in item.get("evidence") or [])]
        if len(matches) != 1:
            stats["ambiguous_or_missing_positive_records_skipped"] += 1
            continue
        positive = matches[0]
        examples.append((candidate_x(positive, inp, packet), True))
        stats["positive_candidates"] += 1
        for q in amounts:
            if q["candidate_id"] != positive["candidate_id"] and q["engine_projection"] != positive["engine_projection"]:
                examples.append((candidate_x(q, inp, packet), False))
                stats["different_value_negative_candidates"] += 1
            elif q["candidate_id"] != positive["candidate_id"]:
                stats["same_value_rivals_unlabeled"] += 1
    return examples, dict(stats)


def fit(records: list[tuple], field: str) -> tuple[SparseLogistic, dict]:
    examples, stats = candidate_examples(records, field)
    positives = [x for x, y in examples if y]
    negatives = [x for x, y in examples if not y]
    if not positives or not negatives:
        raise ValueError("candidate_model_class_missing")
    # Balance supervised candidate classes; threshold is subsequently chosen
    # from event-held-out record predictions, not from training probabilities.
    repeats = max(1, round(len(negatives) / len(positives)))
    balanced = examples + [(x, True) for _ in range(repeats - 1) for x in positives]
    model = SparseLogistic()
    model.fit(balanced)
    stats["positive_repeat_factor"] = repeats
    return model, stats


def predict_rows(records: list[tuple], field: str, model: SparseLogistic) -> list[dict]:
    out = []
    for rid, inp, packet, ref in records:
        item = ref["reference_elements"]["amounts"][field.split(".")[1]]
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        ranked = sorted(amounts, key=lambda q: (-model.predict(candidate_x(q, inp, packet)), q["start"]))
        selected = ranked[0] if ranked else None
        out.append({"id": rid, "score": model.predict(candidate_x(selected, inp, packet)) if selected else 0.0,
                    "candidate_id": selected["candidate_id"] if selected else None,
                    "candidate_count": len(amounts),
                    "candidate_projection": selected["engine_projection"] if selected else None,
                    "silver_positive": present(item),
                    "silver_match_if_selected": bool(selected and present(item) and same_value(field, item["value"], selected))})
    return out


def threshold_from_oof(predictions: list[dict]) -> tuple[float, dict]:
    grid = [i / 100 for i in range(5, 96, 5)]
    metric, threshold = max(((measure(predictions, t), t) for t in grid),
                            key=lambda mt: (mt[0]["f1"], -mt[0]["fp"], mt[1]))
    return threshold, metric


def run(teacher_path: Path, originals_path: Path, silver_path: Path, engine_root: Path) -> dict:
    binding_source = engine_root / "app/discretion/binding.py"
    if not binding_source.is_file():
        raise ValueError("engine_binding_missing")
    sys.path.insert(0, str(engine_root.resolve()))
    from app.discretion.binding import bind
    refs = {r["id"]: r for r in rows(silver_path)
            if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals_path)}
    records = []
    for inp in rows(teacher_path):
        rid = inp["id"]
        if rid not in refs:
            continue
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        records.append((rid, inp, build_packet(text, inp, record_id=rid), refs[rid]))
    if {r[0] for r in records} != set(refs):
        raise ValueError("development_scope_mismatch")
    train = [r for r in records if r[3]["metadata"]["split"] == "train"]
    valid = [r for r in records if r[3]["metadata"]["split"] == "valid"]
    train_events = {r[3]["metadata"].get("event_id") or r[0] for r in train}
    valid_events = {r[3]["metadata"].get("event_id") or r[0] for r in valid}
    if train_events & valid_events:
        raise ValueError("event_split_leakage")
    fields = {}
    for field in FIELDS:
        oof = []
        for fold in range(5):
            fit_records = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) != fold]
            held = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) == fold]
            model, _ = fit(fit_records, field)
            oof.extend(predict_rows(held, field, model))
        threshold, train_metric = threshold_from_oof(oof)
        model, training_stats = fit(train, field)
        valid_rows = predict_rows(valid, field, model)
        fields[field] = {"training_stats": training_stats, "threshold_selected_on_train_oof": threshold,
                         "train_oof": train_metric, "valid": measure(valid_rows, threshold),
                         "valid_original_s2": original_s2(valid, field, bind),
                         "valid_always_select_if_candidate": measure(valid_rows, 0.0),
                         "valid_predictions": valid_rows}
    return {"scope": "silver_supervised_candidate_vs_nil",
            "reference_status": "silver_high_confidence_operational_reference",
            "test_split_used": False, "train_records": len(train), "valid_records": len(valid),
            "train_events": len(train_events), "valid_events": len(valid_events),
            "fields": fields,
            "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
                             "original_s2_binding_py": hashlib.sha256(binding_source.read_bytes()).hexdigest()},
            "limitations": ["Silver-missing amounts are operational negatives under current label confidence",
                            "Broad or duplicate silver evidence is skipped for positive candidate training",
                            "This predicts field-to-amount candidates, not explicit person or event graph edges"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "engine_root", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver, args.engine_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({f: {k: v for k, v in d.items() if k != "valid_predictions"}
                      for f, d in result["fields"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

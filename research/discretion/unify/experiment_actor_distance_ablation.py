"""Ablate target-distance features in weakly supervised amount ranking.

Measures evidence-candidate selection, not true person-edge accuracy. Train
folds are separated by event and valid is held out until model choice is fixed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows
from experiment_pairwise_binding_ranker import candidate_features, dot, train_ranker
from experiment_selective_binding import event_fold, weak_truth
from experiment_weak_role_model import FIELDS, LABELS, weak_labels
from supply_packet import build_packet


def features(q: dict, inp: dict, packet: dict, *, distance: bool) -> Counter:
    x = candidate_features(q, packet, inp["target"], inp.get("aliases") or [])
    if not distance:
        for key in list(x):
            if key.startswith("target_distance:") or key == "target_not_in_view":
                del x[key]
    return x


def training_cases(records: list[tuple], field: str, label: str, *, distance: bool) -> list[tuple]:
    cases = []
    for rid, inp, packet, ref in records:
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        by_id = {q["candidate_id"]: q for q in amounts}
        positive_ids = [qid for qid, role in weak_labels(packet, ref["reference_elements"]).items()
                        if role == label and qid in by_id]
        if len(positive_ids) != 1:
            continue
        positive = by_id[positive_ids[0]]
        negatives = [q for q in amounts if q["candidate_id"] != positive["candidate_id"]
                     and q["engine_projection"] != positive["engine_projection"]]
        if negatives:
            cases.append((features(positive, inp, packet, distance=distance),
                          [features(q, inp, packet, distance=distance) for q in negatives]))
    return cases


def score(records: list[tuple], weights: dict, field: str, *, distance: bool,
          multi_target_distinct_events: set[str]) -> list[dict]:
    out = []
    for rid, inp, packet, ref in records:
        item = ref["reference_elements"]["amounts"][field.split(".")[1]]
        positive, weak_id = weak_truth(field, packet, item)
        if not positive:
            continue
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        ranked = sorted(amounts, key=lambda q: (-dot(weights, features(q, inp, packet, distance=distance)),
                                                q["start"]))
        event = ref["metadata"].get("event_id") or rid
        out.append({"id": rid, "event_sha256": hashlib.sha256(event.encode("utf-8")).hexdigest(),
                    "multi_target_distinct": event in multi_target_distinct_events,
                    "weak_truth_available": weak_id is not None,
                    "candidate_count": len(amounts),
                    "selected_id": ranked[0]["candidate_id"] if ranked else None,
                    "exact_weak_edge_match": bool(weak_id is not None and ranked and
                                                  ranked[0]["candidate_id"] == weak_id)})
    return out


def summarize(rows_: list[dict]) -> dict:
    c = Counter()
    for row in rows_:
        c["silver_positive"] += 1
        if row["weak_truth_available"]:
            c["evaluable"] += 1
            c["exact_weak_edge_match" if row["exact_weak_edge_match"] else "exact_weak_edge_disagree"] += 1
        if row["multi_target_distinct"]:
            c["distinct_multi_target_positive"] += 1
            if row["weak_truth_available"]:
                c["distinct_multi_target_evaluable"] += 1
                c["distinct_multi_target_match" if row["exact_weak_edge_match"]
                  else "distinct_multi_target_disagree"] += 1
    return dict(c)


def distinct_events(records: list[tuple], field: str) -> set[str]:
    by_event = defaultdict(list)
    for rid, _, _, ref in records:
        item = ref["reference_elements"]["amounts"][field.split(".")[1]]
        if item.get("value") is not None and item.get("status") != "未提及":
            by_event[ref["metadata"].get("event_id") or rid].append(json.dumps(item["value"], sort_keys=True))
    return {event for event, values in by_event.items() if len(values) >= 2 and len(set(values)) >= 2}


def run(teacher_path: Path, originals_path: Path, silver_path: Path) -> dict:
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
    for field, label in zip(FIELDS, LABELS):
        train_distinct = distinct_events(train, field)
        valid_distinct = distinct_events(valid, field)
        methods = {}
        for distance in (True, False):
            oof = []
            for fold in range(5):
                fit = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) != fold]
                held = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) == fold]
                weights, _ = train_ranker(training_cases(fit, field, label, distance=distance))
                oof.extend(score(held, weights, field, distance=distance,
                                 multi_target_distinct_events=train_distinct))
            weights, _ = train_ranker(training_cases(train, field, label, distance=distance))
            valid_rows = score(valid, weights, field, distance=distance,
                               multi_target_distinct_events=valid_distinct)
            methods["with_distance" if distance else "without_distance"] = {
                "train_oof": summarize(oof), "valid": summarize(valid_rows),
                "valid_rows": valid_rows}
        fields[field] = {"train_distinct_multi_target_events": len(train_distinct),
                         "valid_distinct_multi_target_events": len(valid_distinct),
                         "methods": methods}
    return {"scope": "event_oof_and_valid_target_distance_ablation", "silver_is_not_gold": True,
            "test_split_used": False, "train_records": len(train), "valid_records": len(valid),
            "fields": fields,
            "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest()},
            "limitations": ["Only target-distance features are removed; masked target text remains in context",
                            "Silver evidence links are weak labels, not human person edges",
                            "Distinct multi-target cases are few"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({f: {m: {k: v for k, v in d.items() if k != "valid_rows"}
                           for m, d in x["methods"].items()} for f, x in result["fields"].items()},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

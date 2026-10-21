"""Learn field-to-amount-candidate ranking from weak silver evidence links.

The field-present oracle is explicit: valid scoring only asks which amount is
the field's value when silver says the field exists. No actor/event gold is
available, and no missing field is treated as a negative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows, same_value
from experiment_weak_role_model import FIELDS, LABELS, CharNB, features, weak_labels
from supply_packet import build_packet


def candidate_features(q: dict, packet: dict, target: str, aliases: list[str]) -> Counter:
    x = features(q, packet, target, aliases)
    mentions = [m for m in packet["mentions"] if m["source_span_id"] == q["source_span_id"]]
    if mentions:
        distance = min(max(0, q["start"] - m["end"]) if m["end"] <= q["start"]
                       else max(0, m["start"] - q["end"]) for m in mentions)
        bucket = "0-8" if distance <= 8 else "9-24" if distance <= 24 else "25-64" if distance <= 64 else "far"
        x["target_distance:" + bucket] += 1
    else:
        x["target_not_in_view"] += 1
    same_scene = [a for a in packet["quantities"] if a["type"] == "amount" and a["scene_id"] == q["scene_id"]]
    x["scene_amount_count:" + str(min(len(same_scene), 5))] += 1
    return x


def dot(weights: defaultdict, x: Counter) -> float:
    return sum(weights[k] * v for k, v in x.items())


def train_ranker(cases: list[tuple[Counter, list[Counter]]], epochs: int = 8) -> tuple[defaultdict, dict]:
    weights = defaultdict(float)
    stats = Counter()
    for _ in range(epochs):
        for positive, negatives in cases:
            for negative in negatives:
                stats["pairs_seen"] += 1
                if dot(weights, positive) - dot(weights, negative) < 1.0:
                    stats["margin_updates"] += 1
                    for feature, value in (positive - negative).items():
                        weights[feature] += 0.05 * value
                    for feature, value in (negative - positive).items():
                        weights[feature] -= 0.05 * value
    return weights, dict(stats)


def run(teacher_path: Path, originals_path: Path, silver_path: Path) -> dict:
    refs = {r["id"]: r for r in rows(silver_path)
            if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals_path)}
    inputs, packets = {}, {}
    for inp in rows(teacher_path):
        rid = inp["id"]
        if rid not in refs:
            continue
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        inputs[rid] = inp
        packets[rid] = build_packet(text, inp, record_id=rid)
    if set(packets) != set(refs):
        raise ValueError("development_scope_mismatch")
    train_events = {r["metadata"].get("event_id") for r in refs.values() if r["metadata"]["split"] == "train"}
    valid_events = {r["metadata"].get("event_id") for r in refs.values() if r["metadata"]["split"] == "valid"}
    if train_events & valid_events:
        raise ValueError("event_split_leakage")
    training = {field: [] for field in FIELDS}
    role_examples = []
    train_counts = Counter()
    for rid, ref in refs.items():
        if ref["metadata"]["split"] != "train":
            continue
        inp, packet = inputs[rid], packets[rid]
        labels = weak_labels(packet, ref["reference_elements"])
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        by_id = {q["candidate_id"]: q for q in amounts}
        for qid, label in labels.items():
            role_examples.append((features(by_id[qid], packet, inp["target"], inp.get("aliases") or []), label))
        for field, label in zip(FIELDS, LABELS):
            positives = [by_id[qid] for qid, value in labels.items() if value == label]
            if len(positives) != 1:
                continue
            positive = positives[0]
            negatives = [q for q in amounts if q["candidate_id"] != positive["candidate_id"]
                         and q["engine_projection"] != positive["engine_projection"]]
            if not negatives:
                train_counts[field + ":no_distinct_negative"] += 1
                continue
            x_pos = candidate_features(positive, packet, inp["target"], inp.get("aliases") or [])
            x_neg = [candidate_features(q, packet, inp["target"], inp.get("aliases") or []) for q in negatives]
            training[field].append((x_pos, x_neg))
            train_counts[field + ":positive_records"] += 1
            train_counts[field + ":pairs"] += len(x_neg)
    model = CharNB()
    model.fit(role_examples)
    weights = {}
    training_stats = {}
    for field in FIELDS:
        weights[field], training_stats[field] = train_ranker(training[field])
    totals = defaultdict(lambda: defaultdict(Counter))
    examples = []
    predictions = []
    for rid, ref in refs.items():
        if ref["metadata"]["split"] != "valid":
            continue
        inp, packet = inputs[rid], packets[rid]
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        for field, label in zip(FIELDS, LABELS):
            item = ref["reference_elements"]["amounts"][field.split(".")[1]]
            if item.get("value") is None or item.get("status") == "未提及":
                continue
            evidence_matches = [q for q in amounts if same_value(field, item["value"], q)
                                and any(e["start"] <= q["start"] < q["end"] <= e["end"]
                                        for e in item.get("evidence") or []
                                        if type(e.get("start")) is int and type(e.get("end")) is int)]
            for method in ("pairwise_ranker", "naive_bayes_ranker"):
                c = totals[method][field]
                c["silver_positive"] += 1
                c["unique_silver_candidate" if len(evidence_matches) == 1 else
                  "same_value_collision" if len(evidence_matches) > 1 else
                  "no_evidence_local_value_candidate"] += 1
                if not amounts:
                    c["no_amount_candidates"] += 1
                    continue
                if method == "pairwise_ranker":
                    ranked = sorted(amounts, key=lambda q: (-dot(weights[field], candidate_features(
                        q, packet, inp["target"], inp.get("aliases") or [])), q["start"]))
                else:
                    ranked = sorted(amounts, key=lambda q: (-model.predict_proba(features(
                        q, packet, inp["target"], inp.get("aliases") or []))[label], q["start"]))
                selected = ranked[0]
                value_match = same_value(field, item["value"], selected)
                evidence_match = any(e["start"] <= selected["start"] < selected["end"] <= e["end"]
                                     for e in item.get("evidence") or []
                                     if type(e.get("start")) is int and type(e.get("end")) is int)
                c["silver_value_match" if value_match else "silver_value_disagree"] += 1
                c["silver_evidence_span_match" if evidence_match else "silver_evidence_span_disagree"] += 1
                if len(evidence_matches) == 1:
                    c["exact_weak_edge_match" if selected["candidate_id"] == evidence_matches[0]["candidate_id"]
                      else "exact_weak_edge_disagree"] += 1
                elif len(evidence_matches) > 1 and value_match:
                    c["collision_value_match_edge_unresolved"] += 1
                predictions.append({"id": rid, "event_sha256": hashlib.sha256(
                    (ref["metadata"].get("event_id") or rid).encode("utf-8")).hexdigest(),
                    "method": method, "field": field, "selected_candidate_id": selected["candidate_id"],
                    "selected_start": selected["start"], "selected_end": selected["end"],
                    "selected_projection": selected["engine_projection"],
                    "silver_value_match": value_match,
                    "exact_weak_edge_match": len(evidence_matches) == 1 and
                    selected["candidate_id"] == evidence_matches[0]["candidate_id"]})
                if not value_match and len(examples) < 15:
                    examples.append({"id": rid, "method": method, "field": field,
                                     "selected_candidate_id": selected["candidate_id"],
                                     "candidate_count": len(amounts)})
    return {"scope": "train_fit_valid_oracle_field_presence", "silver_is_not_gold": True,
            "test_split_used": False, "train_records": 140, "valid_records": 23,
            "train_weak_examples": dict(Counter(label for _, label in role_examples)),
            "train_pairwise": dict(train_counts), "training_stats": training_stats,
            "valid_results": {m: {f: dict(c) for f, c in by_field.items()} for m, by_field in totals.items()},
            "valid_disagreement_examples": examples,
            "valid_predictions": predictions,
            "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest()},
            "limitations": ["Field presence and candidate set are given at evaluation; not deployable output accuracy",
                            "Pairwise negative means different value from one silver evidence match, not human negative edge",
                            "Actor and event edges are not supervised or validated",
                            "Same-value collisions cannot establish person binding from silver value agreement",
                            "Only 5 personal and 7 onsite silver-positive valid records"]}


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
    print(json.dumps({"train_pairwise": result["train_pairwise"],
                      "valid_results": result["valid_results"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

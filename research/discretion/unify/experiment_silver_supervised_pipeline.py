"""Train amount-field presence from silver and evaluate full field outputs.

Train thresholds come from event-held-out out-of-fold predictions. Valid is
evaluated once. Candidate ranking uses the existing weak-evidence pairwise
ranker; silver-missing is now an operational negative for presence learning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows, same_value
from experiment_actor_distance_ablation import training_cases
from experiment_pairwise_binding_ranker import candidate_features, dot, train_ranker
from experiment_selective_binding import event_fold
from experiment_weak_role_model import FIELDS, LABELS
from supply_packet import build_packet


def present(item: dict) -> bool:
    return item.get("value") is not None and item.get("status") != "未提及"


def record_features(inp: dict, packet: dict) -> dict[str, float]:
    amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
    x = Counter()
    x["amount_count:" + str(min(len(amounts), 5))] = 1
    for q in amounts:
        x.update(candidate_features(q, packet, inp["target"], inp.get("aliases") or []))
        role = q.get("role_hint") or "untyped"
        actor = q.get("actor_status") or "unresolved"
        x["any_role:" + role] = 1
        x["any_actor:" + actor] = 1
        x["role_actor:" + role + ":" + actor] = 1
    # Document-level presence uses presence of a context clue, not how often
    # a repeated money list happens to contain that character n-gram.
    return {key: 1 / math.sqrt(len(x)) for key in x}


class SparseLogistic:
    def __init__(self) -> None:
        self.weights = defaultdict(float)
        self.bias = 0.0

    def fit(self, examples: list[tuple[dict[str, float], bool]], *, epochs: int = 220,
            learning_rate: float = 0.7, l2: float = 0.003) -> None:
        if not examples or len({y for _, y in examples}) != 2:
            raise ValueError("presence_training_needs_both_classes")
        self.bias = math.log((sum(y for _, y in examples) + 0.5) /
                             (sum(not y for _, y in examples) + 0.5))
        n = len(examples)
        for _ in range(epochs):
            gradient = Counter()
            bias_gradient = 0.0
            for x, y in examples:
                diff = self.predict(x) - int(y)
                bias_gradient += diff
                for key, value in x.items():
                    gradient[key] += diff * value
            for key in set(self.weights) | set(gradient):
                self.weights[key] -= learning_rate * (gradient[key] / n + l2 * self.weights[key])
            self.bias -= learning_rate * bias_gradient / n

    def predict(self, x: dict[str, float]) -> float:
        score = self.bias + sum(self.weights[key] * value for key, value in x.items())
        score = max(-30.0, min(30.0, score))
        return 1.0 / (1.0 + math.exp(-score))


def train_models(records: list[tuple], field: str, label: str) -> tuple[SparseLogistic, dict]:
    model = SparseLogistic()
    model.fit([(record_features(inp, packet), present(ref["reference_elements"]["amounts"][field.split(".")[1]]))
               for _, inp, packet, ref in records])
    weights, _ = train_ranker(training_cases(records, field, label, distance=True))
    return model, weights


def predict_rows(records: list[tuple], field: str, model: SparseLogistic, weights: dict) -> list[dict]:
    out = []
    for rid, inp, packet, ref in records:
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        ranked = sorted(amounts, key=lambda q: (-dot(weights, candidate_features(
            q, packet, inp["target"], inp.get("aliases") or [])), q["start"]))
        item = ref["reference_elements"]["amounts"][field.split(".")[1]]
        selected = ranked[0] if ranked else None
        out.append({"id": rid, "score": model.predict(record_features(inp, packet)),
                    "candidate_id": selected["candidate_id"] if selected else None,
                    "candidate_count": len(amounts),
                    "candidate_projection": selected["engine_projection"] if selected else None,
                    "silver_positive": present(item),
                    "silver_match_if_selected": bool(selected and present(item) and same_value(field, item["value"], selected))})
    return out


def measure(predictions: list[dict], threshold: float) -> dict:
    c = Counter()
    for row in predictions:
        c["records"] += 1
        c["silver_positive" if row["silver_positive"] else "silver_missing"] += 1
        chosen = row["candidate_id"] is not None and row["score"] >= threshold
        if chosen:
            c["selected"] += 1
            if row["silver_match_if_selected"]:
                c["exact_field_match"] += 1
                c["tp"] += 1
            else:
                c["fp"] += 1
                if row["silver_positive"]:
                    c["wrong_value_on_positive"] += 1
                    c["fn"] += 1
                else:
                    c["output_on_silver_missing"] += 1
        elif row["silver_positive"]:
            c["fn"] += 1
            c["abstain_on_positive"] += 1
        else:
            c["tn"] += 1
    for key in ("tp", "fp", "fn", "tn", "exact_field_match", "output_on_silver_missing"):
        c[key] += 0
    c["f1"] = 2 * c["tp"] / max(1, 2 * c["tp"] + c["fp"] + c["fn"])
    c["presence_recall"] = (c["selected"] - c["output_on_silver_missing"]) / max(1, c["silver_positive"])
    return dict(c)


def threshold_from_oof(predictions: list[dict]) -> tuple[float, dict]:
    grid = [i / 100 for i in range(5, 96, 5)]
    scored = [(measure(predictions, t), t) for t in grid]
    # Prefer the simpler conservative tie choice. Never inspect valid here.
    best, threshold = max(scored, key=lambda mt: (mt[0]["f1"], -mt[0]["fp"], mt[1]))
    return threshold, best


def original_s2(records: list[tuple], field: str, bind) -> dict:
    predictions = []
    for rid, inp, packet, ref in records:
        item = ref["reference_elements"]["amounts"][field.split(".")[1]]
        old = bind(inp["sentence_view"], inp["target"], inp.get("aliases") or (),
                   behavior_date=ref["metadata"].get("behavior_date"))
        bound = old.bindings.get(field)
        predictions.append({"id": rid, "score": 1.0,
                            "candidate_id": bound.candidate_id if bound else None,
                            "silver_positive": present(item),
                            "silver_match_if_selected": bool(bound and present(item) and same_value(
                                field, item["value"], {"engine_projection": bound.value}))})
    return measure(predictions, 0.5)


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
    for field, label in zip(FIELDS, LABELS):
        oof = []
        for fold in range(5):
            fit = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) != fold]
            held = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) == fold]
            model, weights = train_models(fit, field, label)
            oof.extend(predict_rows(held, field, model, weights))
        threshold, train_metric = threshold_from_oof(oof)
        model, weights = train_models(train, field, label)
        valid_rows = predict_rows(valid, field, model, weights)
        train_old_metric = original_s2(train, field, bind)
        valid_old_metric = original_s2(valid, field, bind)
        valid_new_metric = measure(valid_rows, threshold)
        selected_policy = "learned_presence_plus_ranker" if train_metric["f1"] > train_old_metric["f1"] else "original_s2"
        fields[field] = {"threshold_selected_on_train_oof": threshold,
                         "train_oof": train_metric,
                         "train_original_s2": train_old_metric,
                         "policy_selected_on_train": selected_policy,
                         "valid_selected_policy": valid_new_metric if selected_policy == "learned_presence_plus_ranker" else valid_old_metric,
                         "valid": valid_new_metric,
                         "valid_original_s2": valid_old_metric,
                         "valid_always_select_if_candidate": measure(valid_rows, 0.0),
                         "valid_never_select": measure(valid_rows, 1.1),
                         "valid_predictions": valid_rows}
    return {"scope": "silver_supervised_presence_plus_weak_pairwise_binding",
            "reference_status": "silver_high_confidence_operational_reference",
            "test_split_used": False, "train_records": len(train), "valid_records": len(valid),
            "train_events": len(train_events), "valid_events": len(valid_events),
            "fields": fields,
            "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
                             "original_s2_binding_py": hashlib.sha256(binding_source.read_bytes()).hexdigest()},
            "known_label_disputes": ["two pilot cases label 40-yuan table fee as personal stake",
                                     "online recharge/loss is not an onsite total",
                                     "public stake 1850-yuan total status unresolved"]}


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

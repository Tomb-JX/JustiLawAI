"""Weak-silver role learning and constrained assignment on frozen valid events.

Only unambiguous evidence-local train candidates become positive role examples.
The valid split is used once for diagnostics, not threshold tuning; test is sealed.
This does not learn person identity or event membership.
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
from experiment_binding_baselines import candidates_for, select_unique
from supply_packet import build_packet

FIELDS = ("amounts.personal_stake", "amounts.onsite_stake_total")
LABELS = ("personal", "onsite")


def features(q: dict, packet: dict, target: str, aliases: list[str]) -> Counter:
    view = next(v for v in packet["visible_spans"] if v["span_id"] == q["source_span_id"])
    start, end = q["start"] - view["start"], q["end"] - view["start"]
    left = view["quote"][max(0, start - 28):start]
    right = view["quote"][end:end + 20]
    for name in sorted({target, *aliases}, key=len, reverse=True):
        if name:
            left, right = left.replace(name, "〈目标〉"), right.replace(name, "〈目标〉")
    result = Counter()
    for side, text in (("L", left), ("R", right)):
        for n in (1, 2, 3):
            result.update(side + ":" + text[i:i + n] for i in range(len(text) - n + 1))
    result["context_start" if start < 8 else "context_later"] += 1
    return result


def weak_labels(packet: dict, elements: dict) -> dict[str, str]:
    labels = defaultdict(set)
    for field, label in zip(FIELDS, LABELS):
        group, name = field.split(".")
        item = elements[group][name]
        if item.get("value") is None or item.get("status") == "未提及":
            continue
        evidence = item.get("evidence") or []
        matches = [q for q in packet["quantities"] if q["type"] == "amount"
                   and q["parse_status"] == "resolved"
                   and any(type(e.get("start")) is int and type(e.get("end")) is int
                           and e["start"] <= q["start"] < q["end"] <= e["end"] for e in evidence)
                   and same_value(field, item["value"], q)]
        if len(matches) == 1:
            labels[matches[0]["candidate_id"]].add(label)
    return {qid: next(iter(ls)) for qid, ls in labels.items() if len(ls) == 1}


class CharNB:
    def __init__(self) -> None:
        self.docs = Counter()
        self.tokens = {label: Counter() for label in LABELS}
        self.totals = Counter()
        self.vocab = set()

    def fit(self, examples: list[tuple[Counter, str]]) -> None:
        for x, label in examples:
            self.docs[label] += 1
            self.tokens[label].update(x)
            self.totals[label] += sum(x.values())
            self.vocab.update(x)
        if any(self.docs[label] == 0 for label in LABELS):
            raise ValueError("class_without_training_examples")

    def predict_proba(self, x: Counter, temperature: float = 1.0) -> dict[str, float]:
        total_docs = sum(self.docs.values())
        logp = {}
        for label in LABELS:
            base = math.log(self.docs[label] / total_docs)
            denom = self.totals[label] + len(self.vocab)
            logp[label] = base + sum(v * math.log((self.tokens[label][k] + 1) / denom)
                                       for k, v in x.items())
        peak = max(logp.values())
        exp = {k: math.exp((v - peak) / temperature) for k, v in logp.items()}
        total = sum(exp.values())
        return {k: v / total for k, v in exp.items()}


def independent(scored: list[tuple[dict, dict]], threshold: float) -> dict[str, dict | None]:
    out = {}
    for label in LABELS:
        ranked = sorted(scored, key=lambda qp: (-qp[1][label], qp[0]["start"]))
        if not ranked or ranked[0][1][label] < threshold:
            out[label] = None
        else:
            out[label] = ranked[0][0]
    return out


def joint(scored: list[tuple[dict, dict]], threshold: float) -> dict[str, dict | None]:
    # Two-field exact maximum-weight matching, with abstain as a zero-utility
    # option and candidate exclusivity as the global constraint.
    options = {}
    for label in LABELS:
        options[label] = [(None, 0.0)]
        for q, p in scored:
            if p[label] >= threshold:
                utility = math.log(p[label] / max(1e-12, 1 - p[label]))
                options[label].append((q, utility))
    best = (-float("inf"), None, None)
    for qa, wa in options["personal"]:
        for qb, wb in options["onsite"]:
            if qa is not None and qb is not None and qa["candidate_id"] == qb["candidate_id"]:
                continue
            score_ = wa + wb
            if score_ > best[0]:
                best = (score_, qa, qb)
    return {"personal": best[1], "onsite": best[2]}


def measure(totals: defaultdict, method: str, field: str, selected: dict | None, silver_item: dict) -> None:
    c = totals[method][field]
    c["records"] += 1
    positive = silver_item.get("value") is not None and silver_item.get("status") != "未提及"
    c["silver_positive" if positive else "silver_missing"] += 1
    if selected is None:
        c["abstain"] += 1
        return
    c["selected"] += 1
    if positive:
        c["silver_match" if same_value(field, silver_item["value"], selected)
          else "silver_disagree"] += 1
    else:
        c["silver_missing_selected"] += 1


def run(teacher_path: Path, originals_path: Path, silver_path: Path, engine_root: Path) -> dict:
    binding_source = engine_root / "app/discretion/binding.py"
    if not binding_source.is_file():
        raise ValueError("original_s2_unavailable")
    sys.path.insert(0, str(engine_root.resolve()))
    from app.discretion.binding import bind
    refs = {r["id"]: r for r in rows(silver_path)
            if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals_path)}
    packets = {}
    inputs = {}
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
    train, valid = [], []
    grouped_train = []
    for rid in refs:
        labels = weak_labels(packets[rid], refs[rid]["reference_elements"])
        destination = train if refs[rid]["metadata"]["split"] == "train" else valid
        for q in packets[rid]["quantities"]:
            if q["candidate_id"] in labels:
                x = features(q, packets[rid], inputs[rid]["target"], inputs[rid].get("aliases") or [])
                label = labels[q["candidate_id"]]
                destination.append((x, label))
                if destination is train:
                    grouped_train.append((refs[rid]["metadata"].get("event_id") or rid, x, label))
    fold_data = []
    for event_id, x, label in grouped_train:
        fold = int(hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:8], 16) % 5
        fold_data.append((fold, x, label))
    out_of_fold = []
    fold_sizes = Counter()
    for fold in range(5):
        training = [(x, label) for group, x, label in fold_data if group != fold]
        held = [(x, label) for group, x, label in fold_data if group == fold]
        if not held:
            continue
        fold_model = CharNB()
        fold_model.fit(training)
        fold_sizes[str(fold)] = len(held)
        out_of_fold.extend((fold_model.predict_proba(x), label) for x, label in held)
    temperature_grid = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
    # Re-temperature already normalized binary probabilities. This is
    # equivalent to softmax(log score / T), with OOF predictions only.
    def calibrated(p: dict, temperature: float) -> dict:
        weights = {k: max(v, 1e-300) ** (1 / temperature) for k, v in p.items()}
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}
    nll = {str(t): sum(-math.log(max(calibrated(p, t)[label], 1e-300))
                       for p, label in out_of_fold) / len(out_of_fold)
           for t in temperature_grid}
    selected_temperature = min(temperature_grid, key=lambda t: nll[str(t)])
    model = CharNB()
    model.fit(train)
    weak_valid = Counter()
    for x, label in valid:
        weak_valid["examples"] += 1
        p = model.predict_proba(x, selected_temperature)
        weak_valid["correct"] += max(p, key=p.get) == label
    totals = defaultdict(lambda: defaultdict(Counter))
    thresholds = (0.5, 0.8, 0.95)
    for rid, ref in refs.items():
        if ref["metadata"]["split"] != "valid":
            continue
        inp, packet = inputs[rid], packets[rid]
        scored = [(q, model.predict_proba(features(q, packet, inp["target"], inp.get("aliases") or []),
                                            selected_temperature))
                  for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        for threshold in thresholds:
            for name, chooser in (("independent", independent), ("joint", joint)):
                picks = chooser(scored, threshold)
                for field, label in zip(FIELDS, LABELS):
                    measure(totals, f"{name}@{threshold}", field, picks[label],
                            ref["reference_elements"]["amounts"][field.split(".")[1]])
        for field in FIELDS:
            _, q = select_unique(candidates_for(field, packet["quantities"],
                                                guard_actor=False, evidence=None))
            measure(totals, "role_rule", field, q,
                    ref["reference_elements"]["amounts"][field.split(".")[1]])
        old = bind(inp["sentence_view"], inp["target"], inp.get("aliases") or (),
                   behavior_date=ref["metadata"].get("behavior_date"))
        for field in FIELDS:
            binding = old.bindings.get(field)
            q = {"engine_projection": binding.value} if binding is not None else None
            measure(totals, "original_s2", field, q,
                    ref["reference_elements"]["amounts"][field.split(".")[1]])
    return {"scope": "train_fit_valid_evaluate_only", "silver_is_not_gold": True,
            "test_split_used": False, "train_records": sum(r["metadata"]["split"] == "train" for r in refs.values()),
            "valid_records": sum(r["metadata"]["split"] == "valid" for r in refs.values()),
            "train_events": len(train_events), "valid_events": len(valid_events),
            "train_weak_examples": dict(Counter(label for _, label in train)),
            "valid_weak_examples": dict(Counter(label for _, label in valid)),
            "train_event_oof_calibration": {"fold_sizes": dict(fold_sizes),
                                            "temperature_nll": nll,
                                            "selected_temperature": selected_temperature},
            "valid_weak_role_classification": dict(weak_valid),
            "methods": {m: {f: dict(c) for f, c in by_field.items()} for m, by_field in totals.items()},
            "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
                             "original_s2_binding_py": hashlib.sha256(binding_source.read_bytes()).hexdigest()},
            "limitations": ["Training labels are inferred from silver evidence and value, not human edges",
                            "No negative edges are mined from silver-missing fields",
                            "The model learns amount roles only, not actor or event identity",
                            "Threshold sweep is descriptive; valid must not be used to choose a final threshold",
                            "Binary class probabilities are complementary, so candidate exclusivity is usually vacuous at thresholds >= 0.5",
                            "No true event/person constraints are tested"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "engine_root", "out"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver, args.engine_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"train_weak_examples": result["train_weak_examples"],
                      "valid_weak_role_classification": result["valid_weak_role_classification"],
                      "methods": result["methods"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

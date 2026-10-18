"""Freeze event-disjoint small-batch plans; evaluate only independent references."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from durable_calls import read_rows
from element_contract import digest, engine_contract
from s1 import data_root

VERSION = "experiment-plan-1"


def select_events(records, *, n, seed="seg-v2-20261018", exclude_events=()):
    if type(n) is not int or not 0 < n <= 36:
        raise ValueError("small_batch_requires_1_to_36_events")
    events, seen, splits = {}, set(), {}
    for r in records:
        splits.setdefault(r['event_id'], set()).add(r['development_split'])
    if any(len(s) != 1 or not s <= {'train', 'validation', 'test'} for s in splits.values()):
        raise ValueError('event_crosses_development_split')
    for r in records:
        if r["id"] in seen:
            raise ValueError("duplicate_record_id")
        seen.add(r["id"])
        if r["development_split"] == "test" or r["event_id"] in exclude_events:
            continue
        events.setdefault(r["event_id"], []).append(r)
    selected, counts = [], Counter()
    while events and len(selected) < n:
        candidates = [min(group, key=lambda r: digest({"seed": seed, "id": r["id"]})) for group in events.values()]
        def score(r):
            strata = ["batch:" + str(r.get("source_batch")), "form:" + str(r.get("form"))]
            return (sum(counts[s] for s in strata), digest({"seed": seed, "event": r["event_id"]}))
        row = min(candidates, key=score)
        selected.append(row)
        counts["batch:" + str(row.get("source_batch"))] += 1
        counts["form:" + str(row.get("form"))] += 1
        del events[row["event_id"]]
    return {"version": VERSION, "seed": seed, "requested_events": n, "selected_events": len(selected),
            "ids": [r["id"] for r in selected], "event_ids": [r["event_id"] for r in selected],
            "strata": dict(counts), "formal_test_used": False, "execute": False,
            "selection_inputs": "source_batch/form only; no observed outcomes", "release_approved": False}


def evaluate_reference(predictions, references, engine):
    pred = {}
    for row in predictions:
        if row["id"] in pred:
            raise ValueError("duplicate_prediction_id")
        pred[row["id"]] = row
    metrics = {path: Counter() for path in engine.FIELD_INFO}
    seen = set()
    for ref in references:
        if ref["id"] in seen:
            raise ValueError("duplicate_reference_id")
        seen.add(ref["id"])
        if (ref.get("human_review") is not True or not ref.get("independent_reviewer")
                or not ref.get("review_record") or not ref.get("text_orig_sha256")):
            raise ValueError("independent_reference_required:no_model_consensus_as_accuracy")
        original = ref.get("source_text") or ref.get("input", {}).get("text_full") or ""
        if hashlib.sha256(original.encode("utf-8")).hexdigest() != ref["text_orig_sha256"]:
            raise ValueError("reference_source_hash_mismatch")
        if engine.validate_teacher_output(ref.get("elements"), evidence_text=original, located=True):
            raise ValueError("invalid_reference_contract")
        candidate = pred.get(ref["id"], {})
        same_source = candidate.get("text_orig_sha256") == ref["text_orig_sha256"]
        payload = candidate.get("elements")
        valid = same_source and not engine.validate_teacher_output(payload, evidence_text=original, located=True)
        for path in engine.FIELD_INFO:
            g, f = path.split(".")
            truth = ref["elements"][g][f]
            m = metrics[path]
            m["reference_N"] += 1
            m["prediction_valid_N"] += bool(valid)
            correct = bool(valid and payload[g][f]["status"] == truth["status"] and digest(payload[g][f]["value"]) == digest(truth["value"]))
            m["correct_N"] += correct
            if truth["status"] != "未提及":
                m["reference_nonempty_N"] += 1
                m["nonempty_correct_N"] += correct
    return {"version": VERSION, "reference_records": len(seen), "reference_kind": "independently-human-reviewed",
            "fields": {path: {**dict(m), "accuracy": m["correct_N"] / m["reference_N"] if m["reference_N"] else None,
                              "nonempty_accuracy": m["nonempty_correct_N"] / m["reference_nonempty_N"] if m["reference_nonempty_N"] else None}
                       for path, m in metrics.items()}}


def main():
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slice", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--prior-plan", type=Path)
    a = p.parse_args()
    if not a.out.resolve().is_relative_to((data_root() / "s1_runs").resolve()) or a.out.exists():
        p.error("plan 只写新的 $DATA/s1_runs 子目录")
    manifest = json.loads((a.slice / "manifest.json").read_text("utf-8"))
    source = a.slice / "records.jsonl"
    fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()
    if fingerprint != manifest["artifact_hashes"]["records.jsonl"]:
        p.error("切片哈希不匹配")
    prior = json.loads(a.prior_plan.read_text("utf-8")) if a.prior_plan else {}
    plan = select_events(read_rows(source), n=a.n, exclude_events=prior.get("event_ids", []))
    plan.update(slice_records_sha256=fingerprint, prior_plan_hash=digest(prior) if prior else None)
    if prior and prior.get("slice_records_sha256") != fingerprint:
        p.error("前段计划与当前切片不一致")
    if len(prior.get("event_ids", [])) + plan["selected_events"] > 36:
        p.error("前后两段累计事件不得超过 36")
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (a.out / "ids.json").write_text(json.dumps(plan["ids"], ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in plan.items() if k not in ("ids", "event_ids")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

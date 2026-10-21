"""Event-held-out selective amount binding with weak silver evidence.

Silver-missing fields are unlabeled, never training negatives. The train OOF
margin rule is frozen before valid evaluation; test records remain sealed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows, same_value
from experiment_pairwise_binding_ranker import candidate_features, dot, train_ranker
from experiment_weak_role_model import FIELDS, LABELS, weak_labels
from supply_packet import build_packet


def event_fold(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:8], 16) % 5


def cases_for_field(records: list[tuple], field: str, label: str) -> list[tuple]:
    cases = []
    for _, inp, packet, ref in records:
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        by_id = {q["candidate_id"]: q for q in amounts}
        positives = [by_id[qid] for qid, role in weak_labels(packet, ref["reference_elements"]).items()
                     if role == label and qid in by_id]
        if len(positives) != 1:
            continue
        positive = positives[0]
        negatives = [q for q in amounts if q["candidate_id"] != positive["candidate_id"]
                     and q["engine_projection"] != positive["engine_projection"]]
        if negatives:
            cases.append((candidate_features(positive, packet, inp["target"], inp.get("aliases") or []),
                          [candidate_features(q, packet, inp["target"], inp.get("aliases") or [])
                           for q in negatives]))
    return cases


def score_record(weights: dict, inp: dict, packet: dict) -> tuple[dict | None, float | None, int]:
    amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
    ranked = sorted(((dot(weights, candidate_features(q, packet, inp["target"], inp.get("aliases") or [])), q)
                     for q in amounts), key=lambda item: (-item[0], item[1]["start"]))
    if not ranked:
        return None, None, 0
    # A single candidate gives no evidence of preference over an alternative.
    margin = ranked[0][0] - ranked[1][0] if len(ranked) > 1 else None
    return ranked[0][1], margin, len(ranked)


def weak_truth(field: str, packet: dict, item: dict) -> tuple[bool, str | None]:
    positive = item.get("value") is not None and item.get("status") != "未提及"
    if not positive:
        return False, None
    matches = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"
               and same_value(field, item["value"], q)
               and any(type(e.get("start")) is int and type(e.get("end")) is int
                       and e["start"] <= q["start"] < q["end"] <= e["end"]
                       for e in item.get("evidence") or [])]
    return True, matches[0]["candidate_id"] if len(matches) == 1 else None


def evaluate(scored: list[dict], threshold: float, emit_singleton: bool = False) -> dict:
    out = Counter()
    for row in scored:
        out["records"] += 1
        out["silver_positive" if row["silver_positive"] else "silver_missing"] += 1
        if row["silver_positive"] and row["weak_truth_id"] is not None:
            out["evaluable_positive"] += 1
        if row["candidate_count"] == 0:
            out["no_candidate"] += 1
            continue
        if row["margin"] is None and not emit_singleton:
            out["single_candidate_abstain"] += 1
            continue
        if row["margin"] is not None and row["margin"] < threshold:
            out["low_margin_abstain"] += 1
            continue
        out["selected"] += 1
        if not row["silver_positive"]:
            out["silver_missing_selected_unresolved"] += 1
        elif row["weak_truth_id"] is None:
            out["silver_positive_unresolvable_selected"] += 1
        else:
            out["evaluable_selected"] += 1
            out["exact_weak_edge_match" if row["selected_id"] == row["weak_truth_id"]
                else "exact_weak_edge_disagree"] += 1
    return dict(out)


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
    results = {}
    for field, label in zip(FIELDS, LABELS):
        def scored_rows(source: list[tuple], weights: dict) -> list[dict]:
            scored = []
            for rid, inp, packet, ref in source:
                item = ref["reference_elements"]["amounts"][field.split(".")[1]]
                selected, margin, candidate_count = score_record(weights, inp, packet)
                positive, truth_id = weak_truth(field, packet, item)
                scored.append({"id": rid, "event_sha256": hashlib.sha256(
                    (ref["metadata"].get("event_id") or rid).encode("utf-8")).hexdigest(),
                    "selected_id": selected["candidate_id"] if selected else None,
                    "margin": margin, "candidate_count": candidate_count,
                    "silver_positive": positive, "weak_truth_id": truth_id})
            return scored

        oof = []
        for fold in range(5):
            fit = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) != fold]
            held = [r for r in train if event_fold(r[3]["metadata"].get("event_id") or r[0]) == fold]
            weights, _ = train_ranker(cases_for_field(fit, field, label))
            oof.extend(scored_rows(held, weights))
        evaluable = [r for r in oof if r["weak_truth_id"] is not None and r["margin"] is not None]
        margins = sorted({r["margin"] for r in evaluable})
        # This is only an observed weak-label operating point; no confidence
        # guarantee follows from selecting it on these same OOF predictions.
        eligible = []
        for threshold in margins:
            m = evaluate(oof, threshold)
            if m.get("evaluable_selected", 0) >= 10 and m.get("exact_weak_edge_match", 0) * 5 >= 4 * m["evaluable_selected"]:
                eligible.append((m["evaluable_selected"], -threshold, threshold))
        threshold = max(eligible)[2] if eligible else None
        final_weights, training_stats = train_ranker(cases_for_field(train, field, label))
        valid_rows = scored_rows(valid, final_weights)
        results[field] = {
            "train_oof_evaluable_with_margin": len(evaluable),
            "train_oof_forced_margin_zero": evaluate(oof, 0.0),
            "train_oof_selected_threshold": threshold,
            "train_oof_at_threshold": evaluate(oof, threshold) if threshold is not None else None,
            "train_oof_singleton_or_threshold": evaluate(oof, threshold, True) if threshold is not None else None,
            "valid_at_train_threshold": evaluate(valid_rows, threshold) if threshold is not None else None,
            "valid_singleton_or_train_threshold": evaluate(valid_rows, threshold, True) if threshold is not None else None,
            "valid_all_candidates": evaluate(valid_rows, 0.0, True),
            "valid_forced_multi_candidate": evaluate(valid_rows, 0.0),
            "valid_rows": valid_rows,
            "training_stats": training_stats,
        }
    return {"scope": "train_event_oof_threshold_valid_evaluation", "silver_is_not_gold": True,
            "test_split_used": False, "train_records": len(train), "valid_records": len(valid),
            "train_events": len(train_events), "valid_events": len(valid_events),
            "fields": results,
            "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest()},
            "limitations": ["Silver-missing fields are unlabeled; selected outputs there are unresolved, not errors",
                            "Single-candidate records abstain because no pairwise margin exists",
                            "Threshold has only observed weak-label agreement, no calibrated error guarantee",
                            "The actor and event edges are not evaluated"]}


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
    print(json.dumps({f: {k: v for k, v in data.items() if k not in {"valid_rows", "training_stats"}}
                      for f, data in result["fields"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

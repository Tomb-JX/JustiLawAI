"""Score target-projectable exact-span edges after single-human review.

The score is for the selected challenge/control sample only. Derivations and
full field correctness require separate adjudicated projections.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows
from experiment_binding_baselines import FIELDS, candidates_for, select_unique
from supply_packet import build_packet
from validate_edge_review import validate


def score(gold: set[tuple], predicted: set[tuple], unknown: set[tuple]) -> dict:
    known_predictions = predicted - unknown
    tp = len(gold & known_predictions)
    fp = len(known_predictions - gold)
    fn = len(gold - known_predictions)
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = (2 * p * r / (p + r) if p + r else 0.0) if p is not None and r is not None else None
    return {"gold_edges": len(gold), "predicted_known_edges": len(known_predictions),
            "unknown_excluded": len(predicted & unknown), "tp": tp, "fp": fp, "fn": fn,
            "precision": p, "recall": r, "f1": f1}


def target_relation(edge: dict, membership: dict[str, str], field: str) -> str:
    """Return yes/no/unknown for projecting one reviewed edge to the target."""
    if field in {"amounts.personal_stake", "person.age"}:
        actors = edge.get("actor_ids") or []
        return "yes" if "T" in actors else "no" if actors else "unknown"
    event_id = edge.get("event_id")
    if event_id is None:
        return "unknown"
    state = membership.get(event_id)
    return "yes" if state == "asserted" else "no" if state == "negated" else "unknown"


def run(cases_path: Path, review_path: Path, teacher_path: Path,
        originals_path: Path, silver_path: Path, engine_root: Path) -> dict:
    checked = validate(cases_path, review_path)
    if not checked["valid"] or checked["counts"].get("pending") or checked["counts"].get("complete") != checked["cases"]:
        raise ValueError("completed_valid_human_review_required")
    cases = {r["id"]: r for r in rows(cases_path)}
    reviews = {r["id"]: r for r in rows(review_path)}
    if any(not r.get("reviewer_id") for r in reviews.values()):
        raise ValueError("reviewer_identity_required")
    teachers = {r["id"]: r for r in rows(teacher_path) if r["id"] in cases}
    originals = {r["id"]: r["text_full"] for r in rows(originals_path) if r["id"] in cases}
    metadata = {r["id"]: r["metadata"] for r in rows(silver_path) if r["id"] in cases}
    binding_source = engine_root / "app/discretion/binding.py"
    if not binding_source.is_file():
        raise ValueError("original_s2_unavailable")
    sys.path.insert(0, str(engine_root.resolve()))
    from app.discretion.binding import bind

    gold = defaultdict(set)
    unknown = defaultdict(set)
    predicted = {m: defaultdict(set) for m in ("original_s2", "e2_role", "e2_role_actor")}
    unmatched = Counter()
    for rid, case in cases.items():
        inp = teachers[rid]
        text = originals[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != case["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        by_span = defaultdict(list)
        for q in case["candidates"]:
            by_span[(q["start"], q["end"])].append(q["candidate_id"])
        membership = {m["event_id"]: m.get("decision") for m in
                      reviews[rid].get("event_membership_edges", [])
                      if m.get("actor_id") == "T" and m.get("event_id")}
        for edge in reviews[rid]["quantity_edges"]:
            role = edge.get("field_role")
            if edge["decision"] == "uncertain":
                for field in ([role] if role in FIELDS else FIELDS):
                    unknown[field].add((rid, edge["candidate_id"], field))
                continue
            if role not in FIELDS:
                continue
            key = (rid, edge["candidate_id"], role)
            if edge["decision"] == "asserted":
                relation = target_relation(edge, membership, role)
                if relation == "yes":
                    gold[role].add(key)
                elif relation == "unknown":
                    unknown[role].add(key)
        packet = build_packet(text, inp, record_id=rid)
        for field in FIELDS:
            for method, guard in (("e2_role", False), ("e2_role_actor", True)):
                _, q = select_unique(candidates_for(field, packet["quantities"],
                                                    guard_actor=guard, evidence=None))
                if q is not None:
                    predicted[method][field].add((rid, q["candidate_id"], field))
        old = bind(inp["sentence_view"], inp["target"], inp.get("aliases") or (),
                   behavior_date=metadata[rid].get("behavior_date"))
        old_candidates = {q.id: q for q in old.candidates}
        views = {v["id"]: v for v in inp["sentence_view"]}
        for field, binding in old.bindings.items():
            if field not in FIELDS:
                continue
            ids = binding.meta.get("parts") if binding.candidate_id == "AGG-personal" else [binding.candidate_id]
            if not ids:
                unmatched["aggregate_without_parts"] += 1
                continue
            for cid in ids:
                q = old_candidates.get(cid)
                if q is None or q.sentence_id not in views:
                    unmatched["old_candidate_not_located"] += 1
                    continue
                if field == "person.age" and q.kind == "date":
                    unmatched["derived_age_not_direct_edge_scored"] += 1
                    continue
                view = views[q.sentence_id]
                span = (view["start"] + q.start, view["start"] + q.end)
                if text[span[0]:span[1]] != q.text:
                    raise ValueError("old_s2_span_not_source_grounded")
                matches = by_span.get(span, [])
                if not matches:
                    unmatched["old_span_not_in_review_candidates"] += 1
                for qid in matches:
                    predicted["original_s2"][field].add((rid, qid, field))
    results = {method: {field: score(gold[field], by_field[field], unknown[field] - gold[field])
                        for field in FIELDS}
               for method, by_field in predicted.items()}
    return {"scope": "selected_24_train_valid_events", "review_provenance": "single_human_review",
            "population_inference_allowed": False, "metric": "exact_candidate_span_role_and_target_relation",
            "input_sha256": {"cases": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
                             "review": hashlib.sha256(review_path.read_bytes()).hexdigest(),
                             "teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
                             "original_s2_binding_py": hashlib.sha256(binding_source.read_bytes()).hexdigest()},
            "reviewers": sorted({r["reviewer_id"] for r in reviews.values()}),
            "results": results, "unmatched_original_s2": dict(unmatched),
            "limitations": ["Selected challenge/control sample; no population accuracy",
                            "Target-projectable role metric; gold actor/event membership must be explicit",
                            "Original S2 has its own candidate extractor; unmatched spans are separate",
                            "Single human review is not dual-adjudicated gold"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cases", "review", "teacher", "originals", "silver", "engine_root", "out"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output_already_exists")
    result = run(args.cases, args.review, args.teacher, args.originals, args.silver, args.engine_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result["results"], ensure_ascii=False))


if __name__ == "__main__":
    main()

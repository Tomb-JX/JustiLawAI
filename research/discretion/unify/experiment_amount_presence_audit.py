"""Audit observable amount-field presence signals without negative-label claims.

This script does not train or release a presence classifier. It separates
silver-missing records by candidate supply and source-bound lexical signals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows, same_value
from experiment_weak_role_model import FIELDS
from supply_packet import build_packet

ROLE = {"amounts.personal_stake": "personal_stake",
        "amounts.onsite_stake_total": "onsite_stake_total"}


def tier(q: dict, field: str) -> str:
    if q["actor_status"] == "other":
        return "explicit_other_actor"
    if q["role_hint"] == ROLE[field]:
        return "field_role_target" if q["actor_status"] == "target" else "field_role_actor_unresolved"
    if q["role_hint"] is None:
        return "untyped_target" if q["actor_status"] == "target" else "untyped_actor_unresolved"
    return "different_role"


def run(teacher_path: Path, originals_path: Path, silver_path: Path) -> dict:
    refs = {r["id"]: r for r in rows(silver_path)
            if r.get("metadata", {}).get("split") in {"train", "valid"}}
    origins = {r["id"]: r["text_full"] for r in rows(originals_path)}
    counts = defaultdict(lambda: defaultdict(Counter))
    samples = defaultdict(lambda: defaultdict(list))
    processed = set()
    for inp in rows(teacher_path):
        rid = inp["id"]
        if rid not in refs:
            continue
        text = origins[rid]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        ref = refs[rid]
        split = ref["metadata"]["split"]
        packet = build_packet(text, inp, record_id=rid)
        amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
        processed.add(rid)
        for field in FIELDS:
            item = ref["reference_elements"]["amounts"][field.split(".")[1]]
            positive = item.get("value") is not None and item.get("status") != "未提及"
            status = "silver_positive" if positive else "silver_missing_unlabeled"
            c = counts[split][field]
            prefix = status + ":"
            c[prefix + "records"] += 1
            c[prefix + "no_candidate" if not amounts else prefix + "with_candidate"] += 1
            if amounts:
                c[prefix + "one_candidate" if len(amounts) == 1 else prefix + "multiple_candidates"] += 1
            tiers = Counter(tier(q, field) for q in amounts)
            for name in tiers:
                c[prefix + "any_" + name] += 1
            if positive:
                matches = [q for q in amounts if same_value(field, item["value"], q)
                           and any(type(e.get("start")) is int and type(e.get("end")) is int
                                   and e["start"] <= q["start"] < q["end"] <= e["end"]
                                   for e in item.get("evidence") or [])]
                c[prefix + ("unique_evidence_candidate" if len(matches) == 1 else
                            "multiple_evidence_candidates" if matches else "no_evidence_candidate")] += 1
                if len(matches) == 1:
                    c[prefix + "evidence_tier_" + tier(matches[0], field)] += 1
            else:
                # Hashes and span coordinates permit later audit without
                # publishing the original text or assuming these are errors.
                for q in amounts:
                    name = tier(q, field)
                    if len(samples[field][name]) < 8:
                        samples[field][name].append({"id": rid, "split": split,
                                                     "candidate_id": q["candidate_id"],
                                                     "start": q["start"], "end": q["end"],
                                                     "projection": q["engine_projection"]})
    if processed != set(refs):
        raise ValueError("development_scope_mismatch")
    train_events = {r["metadata"].get("event_id") for r in refs.values() if r["metadata"]["split"] == "train"}
    valid_events = {r["metadata"].get("event_id") for r in refs.values() if r["metadata"]["split"] == "valid"}
    if train_events & valid_events:
        raise ValueError("event_split_leakage")
    return {"scope": "train_valid_presence_signal_audit", "silver_is_not_gold": True,
            "test_split_used": False, "records": len(processed),
            "counts": {s: {f: dict(c) for f, c in fields.items()} for s, fields in counts.items()},
            "silver_missing_samples": {f: dict(tiers) for f, tiers in samples.items()},
            "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                             "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                             "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest()},
            "limitations": ["Role and actor hints are regex-derived diagnostic features",
                            "Silver-missing records are unlabeled, not confirmed field absences",
                            "No presence model is trained or validated by this audit"]}


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
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()

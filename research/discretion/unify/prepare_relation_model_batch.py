"""Freeze 120 fresh, source-grounded S1 views for model-draft edge annotation.

This reuses S3/answer-leakage-qualified S1 outputs; it never invents facts
views from raw text. Similarity clustering is conservative, not event gold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from experiment_participant_list import candidate_lists
from run_elements import load_work

RUNS = ("s1-20261018-segv2-final300", "s1-20261018-segv2-ds300",
        "s1-20261018-segv2-min40d")
SEED = 20261025
SIMILARITY_LIMIT = 0.8


def grams(text: str) -> set[str]:
    value = re.sub(r"\s+", "", text)
    return {value[i:i + 3] for i in range(max(0, len(value) - 2))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, len(a | b))


def flags(inp: dict) -> dict[str, bool]:
    packet = inp["supply_packet"]
    return {"multi_amount": sum(q["type"] == "amount" and q["parse_status"] == "resolved"
                                for q in packet["quantities"]) >= 2,
            "list": bool(candidate_lists(packet, inp["target"], inp["aliases"])),
            "prior": any(s["kind"] == "prior_penalty" for s in packet["scenes"]),
            "birth": any(q["role_hint"] == "birth" for q in packet["quantities"])}


def prepare(data: Path, old_teacher: Path) -> tuple[list[dict], dict]:
    unified = data / "unified_raw/web/20261017-web-r3/records.jsonl"
    parsed = data / "parsed/web/20261017-web-r3/records.jsonl"
    old = list(rows(old_teacher))
    old_hashes = {r["source_sha256"] for r in old}
    old_grams = [grams(r.get("facts_text") or "") for r in old if len(r.get("facts_text") or "") >= 20]
    by_source = {}
    work_counts = {}
    for name in RUNS:
        work, rejected = load_work(data / "s1_runs" / name, unified, parsed)
        work_counts[name] = {"eligible": len(work), "rejected": len(rejected)}
        for rid, rec, inp in work:
            source = inp["source_sha256"]
            if source not in old_hashes and len(inp["facts_text"]) >= 20:
                by_source.setdefault(source, (rid, rec, inp, name))
    kept = []
    excluded_old_similar = excluded_new_similar = 0
    for rid, rec, inp, run_name in by_source.values():
        signature = grams(inp["facts_text"])
        if max((jaccard(signature, old_sig) for old_sig in old_grams), default=0) >= SIMILARITY_LIMIT:
            excluded_old_similar += 1
            continue
        if max((jaccard(signature, existing[1]) for existing in kept), default=0) >= SIMILARITY_LIMIT:
            excluded_new_similar += 1
            continue
        kept.append(((rid, rec, inp, run_name), signature))
    candidates = []
    for (rid, rec, inp, run_name), _ in kept:
        reasons = flags(inp)
        candidates.append({"id": rid, "target": inp["target"], "aliases": inp["aliases"],
                           "source_sha256": inp["source_sha256"], "text_full": rec["_text_full"],
                           "sentence_view": inp["sentence_view"], "view_hash": inp["view_hash"],
                           "facts_text": inp["facts_text"], "meta_text": inp["meta_text"],
                           "source_run": run_name, "flags": reasons,
                           "selection_group": "challenge" if any(reasons.values()) else "random"})
    challenge = [r for r in candidates if r["selection_group"] == "challenge"]
    random_pool = [r for r in candidates if r["selection_group"] == "random"]
    # Retain every difficult multi-amount/list case before sampling birth-only cases.
    rng = random.Random(SEED)
    rng.shuffle(challenge)
    challenge.sort(key=lambda r: (-int(r["flags"]["multi_amount"] or r["flags"]["list"]),
                                  -sum(r["flags"].values())))
    rng.shuffle(random_pool)
    if len(challenge) < 60 or len(random_pool) < 60:
        raise ValueError(f"insufficient_strata:{len(challenge)}:{len(random_pool)}")
    selected = challenge[:60] + random_pool[:60]
    rng.shuffle(selected)
    for i, row in enumerate(selected):
        row["split"] = "train" if i < 60 else "calibration" if i < 80 else "model_draft_holdout"
        row["event_cluster_id"] = "C-" + hashlib.sha256(
            (row["source_sha256"] + "|" + row["id"]).encode()).hexdigest()[:16]
    if len({r["source_sha256"] for r in selected}) != 120 or len({r["id"] for r in selected}) != 120:
        raise ValueError("selected_not_unique")
    manifest = {"version": "relation-model-batch-1", "sample_seed": SEED,
                "selection": "60 challenge and 60 random after S1/S3/leakage and approximate fact dedup",
                "event_cluster_is_heuristic": True, "similarity_limit": SIMILARITY_LIMIT,
                "source_runs": work_counts, "old_teacher_sha256": hashlib.sha256(old_teacher.read_bytes()).hexdigest(),
                "unified_sha256": hashlib.sha256(unified.read_bytes()).hexdigest(),
                "parsed_sha256": hashlib.sha256(parsed.read_bytes()).hexdigest(),
                "fresh_source_candidates": len(by_source), "excluded_old_similar": excluded_old_similar,
                "excluded_new_similar": excluded_new_similar, "remaining_clusters": len(candidates),
                "selected": len(selected), "splits": dict(Counter(r["split"] for r in selected)),
                "strata": dict(Counter(r["selection_group"] for r in selected)),
                "flags": {key: sum(r["flags"][key] for r in selected) for key in
                          ("multi_amount", "list", "prior", "birth")},
                "model_draft_not_gold": True}
    return selected, manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "old_teacher", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    selected, manifest = prepare(args.data, args.old_teacher)
    args.out.mkdir(parents=True)
    path = args.out / "inputs.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in selected), "utf-8")
    manifest["inputs_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

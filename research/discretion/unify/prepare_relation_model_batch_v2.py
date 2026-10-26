"""Freeze a second fresh batch from leakage-remediated teacher inputs.

Excludes every source already in the old 203 teacher set and in earlier relation
batches, then removes near-duplicates (3-gram Jaccard) against them and within
the pool. Near-duplicate pool records are one event cluster; one record per
cluster is kept so splits never share an event. Amount-rich records are
oversampled because the joint amount-role experiment needs them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from experiment_participant_list import candidate_lists
from prepare_relation_model_batch import grams, jaccard
from supply_packet import build_packet

SEED = 20261026
SIMILARITY_LIMIT = 0.8


def flags(packet: dict, target: str, aliases: list[str]) -> dict[str, bool]:
    amounts = [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"]
    return {"multi_amount": len(amounts) >= 2, "any_amount": bool(amounts),
            "list": bool(candidate_lists(packet, target, aliases)),
            "prior": any(s["kind"] == "prior_penalty" for s in packet["scenes"]),
            "birth": any(q["role_hint"] == "birth" for q in packet["quantities"])}


def prepare(teacher: Path, originals: Path, old_teacher: Path, previous: list[Path], *,
            size: int | None, splits: dict[str, int],
            source_run: str = "expansion-1000-20261021/teacher-inputs-v4d") -> tuple[list[dict], dict]:
    """size=None keeps one record from every event cluster (natural distribution, no oversampling);
    the last split then takes whatever remains after the others."""
    texts = {r["id"]: r["text_full"] for r in rows(originals)}
    used_sources, used_grams = set(), []
    for path in [old_teacher, *previous]:
        for r in rows(path):
            used_sources.add(r["source_sha256"])
            if len(r.get("facts_text") or "") >= 20:
                used_grams.append(grams(r["facts_text"]))
    stats = Counter()
    clusters: list[list[tuple[dict, set]]] = []
    for inp in rows(teacher):
        stats["pool"] += 1
        text = texts.get(inp["id"])
        if text is None or hashlib.sha256(text.encode("utf-8")).hexdigest() != inp["source_sha256"]:
            stats["source_missing_or_mismatch"] += 1
            continue
        if inp["source_sha256"] in used_sources or len(inp.get("facts_text") or "") < 20:
            stats["used_source_or_short_facts"] += 1
            continue
        signature = grams(inp["facts_text"])
        if any(jaccard(signature, g) >= SIMILARITY_LIMIT for g in used_grams):
            stats["similar_to_used"] += 1
            continue
        row = {**inp, "text_full": text}
        home = next((c for c in clusters if any(jaccard(signature, s) >= SIMILARITY_LIMIT for _, s in c)), None)
        if home is None:
            clusters.append([(row, signature)])
        else:
            home.append((row, signature))
            stats["same_event_extra_targets"] += 1
    rng = random.Random(SEED)
    candidates = []
    for cluster in clusters:
        row = rng.choice([r for r, _ in cluster])
        packet = build_packet(row["text_full"], row, record_id=row["id"])
        row["flags"] = flags(packet, row["target"], row.get("aliases") or [])
        row["cluster_size"] = len(cluster)
        candidates.append(row)
    rich = [r for r in candidates if r["flags"]["multi_amount"] or r["flags"]["list"]]
    rest = [r for r in candidates if r not in rich]
    rng.shuffle(rich)
    rng.shuffle(rest)
    if size is None:
        size = len(candidates)
        *head, last = splits
        splits = {**{k: splits[k] for k in head}, last: size - sum(splits[k] for k in head)}
    # Amount-rich/list records first (the joint-role target), then a natural-distribution remainder.
    # When the random remainder is short, rich records fill the gap (batches 2–3 never hit this).
    n_rich = min(len(rich), max(size * 2 // 3, size - len(rest)))
    selected = rich[:n_rich] + rest[:size - n_rich]
    if len(selected) < size:
        raise ValueError(f"insufficient_pool:{len(selected)}")
    rng.shuffle(selected)
    order = [name for name, n in splits.items() for _ in range(n)]
    if len(order) != size:
        raise ValueError("split_sizes_do_not_sum_to_size")
    out = []
    for row, split in zip(selected, order):
        out.append({"id": row["id"], "target": row["target"], "aliases": row.get("aliases") or [],
                    "source_sha256": row["source_sha256"], "text_full": row["text_full"],
                    "sentence_view": row["sentence_view"], "view_hash": row["view_hash"],
                    "facts_text": row["facts_text"], "meta_text": row.get("meta_text") or "",
                    "source_run": source_run, "flags": row["flags"],
                    "selection_group": "challenge" if row in rich else "random", "split": split,
                    "event_cluster_id": "C-" + hashlib.sha256(row["source_sha256"].encode()).hexdigest()[:16],
                    "event_cluster_size": row["cluster_size"]})
    manifest = {"version": "relation-model-batch-2", "sample_seed": SEED, "similarity_limit": SIMILARITY_LIMIT,
                "teacher_sha256": hashlib.sha256(teacher.read_bytes()).hexdigest(),
                "excluded_sources_from": [str(p) for p in [old_teacher, *previous]],
                "funnel": dict(stats), "event_clusters": len(clusters), "selected": len(out),
                "splits": dict(Counter(r["split"] for r in out)),
                "strata": dict(Counter(r["selection_group"] for r in out)),
                "flags": {k: sum(r["flags"][k] for r in out) for k in out[0]["flags"]},
                "model_draft_not_gold": True}
    return out, manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "old_teacher", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--previous", type=Path, action="append", default=[])
    ap.add_argument("--size", type=int, default=360, help="0 = every event cluster, natural distribution")
    ap.add_argument("--source-run", default="expansion-1000-20261021/teacher-inputs-v4d")
    ap.add_argument("--splits", default="train=240,calibration=40,model_draft_holdout=80")
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    splits = {k: int(v) for k, v in (x.split("=") for x in args.splits.split(","))}
    selected, manifest = prepare(args.teacher, args.originals, args.old_teacher, args.previous,
                                 size=args.size or None, splits=splits, source_run=args.source_run)
    args.out.mkdir(parents=True)
    path = args.out / "inputs.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in selected), "utf-8")
    manifest["inputs_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

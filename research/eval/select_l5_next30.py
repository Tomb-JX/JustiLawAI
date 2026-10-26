"""Freeze an event-distinct, train-only L5 candidate list; no teacher calls."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


QUOTAS = {"不予处罚": 8, "罚款": 7, "拘留": 7, "拘留并处罚款": 8}
CLUES = ("赌资", "抽头", "获利", "组织", "现场", "分别", "其中")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank(row: dict) -> tuple:
    facts = row["facts_text"]
    return (-sum(word in facts for word in CLUES), row["source_batch"], row["id"])


def main() -> None:
    p = argparse.ArgumentParser()
    for name in ("pool", "canary", "mixed_model", "mixed_manual"):
        p.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    paths = {name: getattr(a, name) for name in ("pool", "canary", "mixed_model", "mixed_manual")}
    pool = [r for r in rows(a.pool) if r["split"] == "train" and r["channel"] == "pkulaw"]
    prior = rows(a.canary) + rows(a.mixed_model) + rows(a.mixed_manual)
    prior_ids = {r["id"] for r in prior}
    prior_events = {r["event_id"] for r in prior}
    if len(pool) != 272 or len(prior_ids) != 60 or len(prior_events) != 60:
        raise ValueError("frozen L5 pool or previous selections changed")
    untouched = [r for r in pool if r["event_id"] not in prior_events]
    if len(untouched) != 108 or len({r["event_id"] for r in untouched}) != 79:
        raise ValueError("untouched event pool changed")
    selected, used_events = [], set(prior_events)
    for outcome, target in QUOTAS.items():
        candidates = sorted((r for r in untouched if r["observed_outcome"]["type"] == outcome), key=rank)
        for row in candidates:
            if row["event_id"] in used_events:
                continue
            selected.append({
                "id": row["id"], "event_id": row["event_id"], "source_batch": row["source_batch"],
                "outcome_type": outcome, "cue_count": -rank(row)[0], "source_text_sha256": row["source_text_sha256"],
            })
            used_events.add(row["event_id"])
            if sum(x["outcome_type"] == outcome for x in selected) == target:
                break
        if sum(x["outcome_type"] == outcome for x in selected) != target:
            raise ValueError(f"insufficient distinct events for {outcome}")
    if len(selected) != 30 or len({r["event_id"] for r in selected}) != 30:
        raise ValueError("selection is not 30 distinct events")
    a.out.mkdir(parents=True)
    selected_path = a.out / "selected.jsonl"
    with selected_path.open("w", encoding="utf-8", newline="\n") as f:
        for row in selected:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "status": "candidate_only_no_teacher_calls", "release_approved": False,
        "pool_records": len(pool), "pool_events": len({r["event_id"] for r in pool}),
        "prior_records": len(prior_ids), "prior_events": len(prior_events),
        "untouched_records": len(untouched), "untouched_events": len({r["event_id"] for r in untouched}),
        "selected_records": len(selected), "selected_events": len(selected),
        "selected_outcomes": dict(Counter(r["outcome_type"] for r in selected)),
        "selected_batches": dict(Counter(r["source_batch"] for r in selected)),
        "sources": {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()},
        "selected_sha256": sha(selected_path),
        "next_gate": "rebuild current allowed view, audit answer leakage and target binding before L5 calls",
    }
    (a.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in ("selected_records", "selected_events", "selected_outcomes", "selected_batches")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

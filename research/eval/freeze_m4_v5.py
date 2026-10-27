"""One-pass quality closure for the M4 development-silver package.

Rules are fixed before training: remove unusably short facts, internally
contradictory outcomes, and exact facts crossing a frozen validation split.
No sealed test file is read.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


FILES = ("train.jsonl", "old168.jsonl", "lake706_valid70.jsonl", "p3p7_valid119.jsonl", "p9_valid.jsonl")


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm_fact(row: dict) -> str:
    return "".join(row["input"]["facts_text"].split())


def inconsistent(row: dict) -> bool:
    target = row["target"]
    kind, days, fine = target["type"], target["detention_days"], target["fine"]
    return bool((kind == "罚款" and (days != 0 or fine <= 0))
                or (kind == "拘留" and (days <= 0 or fine != 0))
                or (kind == "拘留并处罚款" and (days <= 0 or fine <= 0))
                or (kind in ("不予处罚", "不构成违法", "警告") and (days != 0 or fine != 0)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    parts = {name: read(args.source / name) for name in FILES}
    original_sha = {name: sha(args.source / name) for name in FILES}
    excluded = []
    kept = {}
    for name, rows in parts.items():
        accepted = []
        for row in rows:
            reasons = []
            if len(norm_fact(row)) <= 25:
                reasons.append("facts_le_25_chars")
            if inconsistent(row):
                reasons.append("outcome_internal_inconsistency")
            if reasons:
                excluded.append({"split": name, "id": row["id"], "event_id": row["event_id"],
                                 "reasons": reasons})
            else:
                accepted.append(row)
        kept[name] = accepted

    # Frozen earlier cohorts take precedence; later P9 validation cannot reuse
    # identical facts already in training, even when source IDs differ.
    train_text = {norm_fact(row) for row in kept["train.jsonl"]}
    valid = []
    for row in kept["p9_valid.jsonl"]:
        if norm_fact(row) in train_text:
            excluded.append({"split": "p9_valid.jsonl", "id": row["id"],
                             "event_id": row["event_id"], "reasons": ["exact_train_fact"]})
        else:
            valid.append(row)
    kept["p9_valid.jsonl"] = valid

    # Check all splits, but report legacy cross-split matches instead of silently
    # rewriting historical validation cohorts.
    owners = defaultdict(set)
    for name, rows in kept.items():
        for row in rows:
            owners[norm_fact(row)].add(name)
    cross = sum(len(splits) > 1 for splits in owners.values())
    event_owners = defaultdict(set)
    for name, rows in kept.items():
        for row in rows:
            event_owners[row["event_id"]].add(name)
    if any(len(splits) > 1 for splits in event_owners.values()):
        raise ValueError("Cross-split event after closure")

    args.out.mkdir(parents=True)
    for name, rows in kept.items():
        write(args.out / name, rows)
    write(args.out / "excluded.jsonl", excluded)
    manifest = {
        "status": "frozen_development_silver", "release_approved": False,
        "test_scored": False, "stratified_eval_only": True,
        "parent": str(args.source), "parent_manifest_sha256": sha(args.source / "manifest.json"),
        "source_sha256": original_sha,
        "rules": ["normalized_facts_length>25", "target_type_days_fine_consistent",
                  "P9_valid_exact_fact_not_in_train"],
        "excluded_by_reason": dict(Counter(reason for item in excluded for reason in item["reasons"])),
        "remaining_cross_split_exact_facts": cross,
        "records": {name: len(rows) for name, rows in kept.items()},
        "events": {name: len({row["event_id"] for row in rows}) for name, rows in kept.items()},
        "outputs": {name: sha(args.out / name) for name in (*FILES, "excluded.jsonl")},
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("excluded_by_reason", "remaining_cross_split_exact_facts", "records", "events")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

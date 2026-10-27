"""Descriptive audit of an M4 silver package; reads no sealed test data."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics


FILES = ("train.jsonl", "old168.jsonl", "lake706_valid70.jsonl", "p3p7_valid119.jsonl", "p9_valid.jsonl")


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def audit(rows: list[dict]) -> dict:
    labels = Counter(row["target"]["type"] for row in rows)
    cohorts = Counter(row["metadata"].get("cohort") for row in rows)
    batches = Counter(row["metadata"].get("source_batch") for row in rows)
    events = Counter(row["event_id"] for row in rows)
    lengths = [len(row["input"]["facts_text"].strip()) for row in rows]
    by_type = defaultdict(list)
    for row in rows:
        by_type[row["target"]["type"]].append(row)
    return {
        "records": len(rows), "events": len(events), "labels": labels,
        "cohorts": cohorts, "batches_top10": batches.most_common(10),
        "multi_person_events": sum(n > 1 for n in events.values()),
        "max_event_size": max(events.values(), default=0),
        "facts_length": {"median": statistics.median(lengths),
                         "p10": sorted(lengths)[len(lengths) // 10],
                         "p90": sorted(lengths)[9 * len(lengths) // 10],
                         "le_20": sum(n <= 20 for n in lengths),
                         "le_50": sum(n <= 50 for n in lengths)},
        "by_type": {kind: {"n": len(group),
                           "days_median": statistics.median(row["target"]["detention_days"] for row in group),
                           "fine_median": statistics.median(row["target"]["fine"] for row in group),
                           "fine_top": Counter(row["target"]["fine"] for row in group).most_common(8)}
                    for kind, group in by_type.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    parts = {name: read(args.package / name) for name in FILES if (args.package / name).exists()}
    result = {name: audit(rows) for name, rows in parts.items()}
    text_groups = defaultdict(list)
    for name, rows in parts.items():
        for row in rows:
            key = hashlib.sha256("".join(row["input"]["facts_text"].split()).encode()).hexdigest()
            text_groups[key].append((name, row["id"], row["target"]["type"]))
    result["text_duplicates"] = {
        "groups": sum(len(v) > 1 for v in text_groups.values()),
        "cross_split_groups": sum(len({name for name, _, _ in v}) > 1 for v in text_groups.values()),
        "conflicting_type_groups": sum(len({kind for _, _, kind in v}) > 1 for v in text_groups.values()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

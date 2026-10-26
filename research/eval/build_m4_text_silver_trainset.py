"""Materialize the audited 1740-record M4 facts-only development trainset."""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split(row: dict) -> str:
    return row.get("split") or row["metadata"]["split"]


def facts(row: dict) -> str:
    return row.get("facts_text") or row["input"]["facts_text"]


def dump(path: Path, items: list[dict]) -> str:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return sha(path)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--text-report", type=Path, required=True)
    p.add_argument("--unify", type=Path, required=True)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    os.environ.setdefault("JUSTILAW_ENGINE_API", str(a.repo / "justilaw-api"))
    sys.path.insert(0, str(a.unify))
    from freeze_slice import leak_reasons  # type: ignore

    report = json.loads(a.text_report.read_text("utf-8"))
    sources = {k: Path(v["path"]) for k, v in report["sources"].items()}
    for name, path in sources.items():
        if sha(path) != report["sources"][name]["sha256"]:
            raise ValueError(f"source changed: {name}")
    base, prior, lake, p3, sealed = (rows(sources[k]) for k in
                                    ("base", "prior85", "lake706", "p3p7", "sealed203"))
    queue = {r["id"]: (r["source_batch"], r["source_id"]) for r in rows(sources["queue"])}
    regroup = {(r["batch"], r["id"]): r["new"] for r in rows(sources["regroup"])}
    for row in p3:
        row["event_id"] = regroup.get(queue[row["id"]], row["event_id"])
    cohorts = {"base": base, "prior85": prior, "lake706": lake, "p3p7": p3}
    trains, valids = [], {"old168": [], "lake706_valid70": [], "p3p7_valid119": []}
    provenance = []
    leak_counts = Counter()
    for name, items in cohorts.items():
        for row in items:
            bucket = split(row)
            if bucket not in ("train", "valid"):
                continue
            if bucket == "valid" and name == "prior85":
                # This older validation slice is outside the pinned three-cohort check.
                continue
            text = facts(row)
            if not text or not text.strip():
                raise ValueError(f"empty facts: {row['id']}")
            reasons = leak_reasons(text)
            leak_counts.update(reasons)
            event_id = row.get("event_id") or row["metadata"]["event_id"]
            source_batch = row.get("source_batch") or (row.get("metadata") or {}).get("source_batch")
            channel = row.get("channel") or (row.get("metadata") or {}).get("channel")
            entry = {"id": row["id"], "event_id": event_id,
                     "input": {"facts_text": text},
                     "target": row["observed_outcome"],
                     "metadata": {"cohort": name, "source_batch": source_batch,
                                  "channel": channel, "source_text_sha256": row.get("source_text_sha256")},
                     "label_tier": "development_silver", "human_review": bool(row.get("human_review", False)),
                     "release_approved": False}
            provenance.append({"id": row["id"], "cohort": name,
                               "answer_source": row.get("answer_source"),
                               "decision_evidence": row.get("answer_evidence") or row.get("decision_evidence")})
            if bucket == "train":
                trains.append(entry)
            elif name == "base":
                valids["old168"].append(entry)
            elif name == "lake706":
                valids["lake706_valid70"].append(entry)
            elif name == "p3p7":
                valids["p3p7_valid119"].append(entry)
    if len(trains) != 1740 or tuple(map(len, valids.values())) != (168, 70, 119):
        raise ValueError("frozen train or validation counts changed")
    if leak_counts:
        raise ValueError(f"facts answer leakage: {dict(leak_counts)}")
    all_entries = trains + sum(valids.values(), [])
    ids = [r["id"] for r in all_entries]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate train/validation record ID")
    train_events = {r["event_id"] for r in trains}
    valid_events = {r["event_id"] for r in sum(valids.values(), [])}
    if len(valid_events) != sum(len({r["event_id"] for r in group}) for group in valids.values()):
        raise ValueError("validation event duplicated across cohorts")
    test_events = {r["metadata"]["event_id"] for r in sealed if split(r) == "test"}
    if train_events & (valid_events | test_events) or valid_events & test_events:
        raise ValueError("event split leakage")
    if len(test_events) == 0 or sum(split(r) == "test" for r in sealed) != 40:
        raise ValueError("sealed test census changed")
    a.out.mkdir(parents=True)
    train_sha = dump(a.out / "train.jsonl", trains)
    valid_hashes = {}
    for name, items in valids.items():
        valid_hashes[name] = dump(a.out / f"{name}.jsonl", items)
    provenance_sha = dump(a.out / "answer_provenance.jsonl", provenance)
    manifest = {
        "status": "model_ready_development_silver", "release_approved": False,
        "features_whitelist": ["input.facts_text"],
        "target_fields": ["type", "detention_days", "fine"],
        "train_records": len(trains), "train_events": len(train_events),
        "validation_records": {k: len(v) for k, v in valids.items()},
        "validation_events": {k: len({r["event_id"] for r in v}) for k, v in valids.items()},
        "sealed_test_records_unscored": 40, "test_scored": False,
        "train_classes": dict(Counter(r["target"]["type"] for r in trains)),
        "train_by_cohort": dict(Counter(r["metadata"]["cohort"] for r in trains)),
        "leak_reasons": dict(leak_counts), "cross_split_event_overlap": 0,
        "source_text_report_sha256": sha(a.text_report),
        "source_hashes": {k: report["sources"][k]["sha256"] for k in sources},
        "leak_checker_sha256": sha(a.unify / "freeze_slice.py"),
        "outputs": {"train.jsonl": train_sha, "answer_provenance.jsonl": provenance_sha,
                    **{f"{k}.jsonl": v for k, v in valid_hashes.items()}},
    }
    (a.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in
                      ("status", "train_records", "train_events", "validation_records", "train_classes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

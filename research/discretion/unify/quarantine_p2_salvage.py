"""Freeze a clean S1 input by quarantining the P2-r1 salvage source."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def split_overlap(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, set[str]] = {}
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if all(key):
            groups.setdefault(key, set()).add(row["split"])
    return [{"key": list(key), "splits": sorted(splits)} for key, splits in groups.items() if len(splits) > 1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error("output already exists")
    src_manifest = json.loads((a.input / "MANIFEST.json").read_text("utf-8"))
    records = read_rows(a.input / "records.jsonl")
    no_subject = read_rows(a.input / "no_subject.jsonl")
    if len(records) != 3196 or Counter(r.get("grade") for r in records)["A-salvage"] != 313:
        raise ValueError("unexpected input cohort; audit before quarantine")
    quarantined = [r for r in records if r.get("grade") == "A-salvage" or r.get("source_batch") == "20261018-P2-r1"]
    kept = [r for r in records if r.get("grade") != "A-salvage" and r.get("source_batch") != "20261018-P2-r1"]
    if len(quarantined) != 313 or len(kept) != 2883 or any(r.get("grade") != "A" for r in kept):
        raise ValueError("unexpected quarantine partition")
    no_subject_quarantine = [r for r in no_subject if r.get("source_batch") == "20261018-P2-r1"]
    no_subject_kept = [r for r in no_subject if r.get("source_batch") != "20261018-P2-r1"]
    if len(no_subject_quarantine) != 62:
        raise ValueError("unexpected P2-r1 no-subject count")
    if len({r["id"] for r in kept}) != len(kept) or len({tuple(r["dedup_key"]) for r in kept}) != len(kept):
        raise ValueError("duplicate ID or event-person in retained input")
    event_map: dict[str, dict] = {}
    for r in kept:
        e = event_map.setdefault(r["event_id"], {"event_id": r["event_id"], "split": r["split"],
                                                "records": 0, "source_batches": set(),
                                                "event_key_source": r["event_key_source"]})
        if e["split"] != r["split"]:
            raise ValueError("event crosses split")
        e["records"] += 1
        e["source_batches"].add(r["source_batch"])
    events = [{**e, "source_batches": sorted(e["source_batches"])} for e in event_map.values()]
    old_doc_overlap = split_overlap(records, ("doc_no_hash",))
    new_doc_overlap = split_overlap(kept, ("doc_no_hash",))
    old_train_valid = [x for x in old_doc_overlap if {"train", "valid"}.issubset(x["splits"])]
    new_train_valid = [x for x in new_doc_overlap if {"train", "valid"}.issubset(x["splits"])]
    if new_train_valid:
        raise ValueError(f"train/valid document-hash overlap remains: {len(new_train_valid)}")
    old_sha = hashlib.sha256((a.input / "records.jsonl").read_bytes()).hexdigest()
    a.out.mkdir(parents=True)
    hashes = {
        "records_sha256": write_rows(a.out / "records.jsonl", kept),
        "events_sha256": write_rows(a.out / "events.jsonl", events),
        "no_subject_sha256": write_rows(a.out / "no_subject.jsonl", no_subject_kept),
        "quarantine_records_sha256": write_rows(a.out / "quarantine" / "records.jsonl", quarantined),
        "quarantine_no_subject_sha256": write_rows(a.out / "quarantine" / "no_subject.jsonl", no_subject_quarantine),
    }
    by_batch = Counter(r["source_batch"] for r in kept)
    manifest = {
        "version": "s1-input-p2-quarantine-1", "parent": str(a.input.resolve()),
        "parent_manifest_records_sha256": src_manifest["records_sha256"],
        "parent_records_sha256": old_sha, "records": len(kept), "events": len(events),
        "no_subject_records": len(no_subject_kept), "by_grade": dict(Counter(r["grade"] for r in kept)),
        "by_channel": dict(Counter("web" if r["channel"] == "web" else "pkulaw" for r in kept)),
        "by_split": dict(Counter(r["split"] for r in kept)), "by_batch": dict(by_batch),
        "party_available": sum(bool(r.get("party_available")) for r in kept),
        "quarantine": {"reason": "P2-r1 format_ok=false; salvage lacks source-quality assurance",
                       "records": len(quarantined), "no_subject_records": len(no_subject_quarantine),
                       "source_batch": "20261018-P2-r1"},
        "cross_split": {"old_train_valid_doc_hash": len(old_train_valid),
                        "new_train_valid_doc_hash": len(new_train_valid),
                        "new_exact_text_hash": len(split_overlap(kept, ("text_orig_sha256",))),
                        "new_event_id": len(split_overlap(kept, ("event_id",)))},
        "hashes": hashes,
    }
    if any(manifest["cross_split"][k] for k in ("new_train_valid_doc_hash", "new_exact_text_hash", "new_event_id")):
        raise ValueError("cross-split leakage remains")
    (a.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    report = ["# P2-r1 quarantine 后的 S1 输入", "",
              f"- 来源：`{a.input.resolve()}`，源记录 SHA-256 `{old_sha}`。",
              f"- S1 记录：{len(records)} → **{len(kept)}**；事件：{len(events)}；split：{manifest['by_split']}。",
              f"- `A-salvage` 入 `quarantine/records.jsonl`：**{len(quarantined)}**；P2-r1 无主体另隔离 **{len(no_subject_quarantine)}**。",
              f"- 文号哈希 train/valid 跨集组：{len(old_train_valid)} → **{len(new_train_valid)}**；保留集原文哈希/事件 ID 跨集：0/0。",
              "- quarantine 可追溯，未删除旧批次；筛查不生成教师标签，也不改变固定 final300 口径。",
              "", "## 保留批次", "", "| batch | records |", "|---|---:|"]
    report += [f"| {batch} | {count} |" for batch, count in sorted(by_batch.items())]
    (a.out / "DEDUP_REPORT.md").write_text("\n".join(report) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in ("records", "events", "by_split", "quarantine", "cross_split")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

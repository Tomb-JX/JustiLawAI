"""Legacy experimental three-model-consensus freeze, not the annotation gate.

Usage: python freeze_safe_subset.py <candidate_manifest.json> <delivery.jsonl>
                                   <record_review_queue.csv> <receipts.jsonl> <new_output_dir>
Refuses to write unless all 50 records have hash-bound independent review receipts.
The formal input gate is upstream delivery acceptance plus source-risk disposition.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path

from audit_safe_subset import check_record
from flagship_client import MODELS, REVIEW_TRIO
from sample_pilot_r1 import PILOT_FIELDS


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print(__doc__)
        return 2
    candidate_path, source_path, queue_path, receipt_path, out = map(Path, argv[1:])
    repository = Path(__file__).resolve().parents[2]
    if out.resolve().is_relative_to(repository):
        raise SystemExit("Refusing to place source text inside the repository")
    if out.exists():
        raise SystemExit("Output directory already exists; immutable freeze is never overwritten")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    source_bytes = source_path.read_bytes()
    if sha(source_bytes) != candidate["delivery_file_sha256"]:
        raise SystemExit("Delivery file hash changed")
    entries = candidate["entries"]
    wanted = {entry["id"]: entry for entry in entries}
    if len(entries) != 50 or len(wanted) != 50:
        raise SystemExit("Exactly 50 unique candidate IDs required")
    with queue_path.open(encoding="utf-8-sig", newline="") as handle:
        queue_rows = list(csv.DictReader(handle))
    queue = {item["id"]: item for item in queue_rows}
    if len(queue_rows) != 50 or set(queue) != set(wanted):
        raise SystemExit("Review queue must match all 50 candidate IDs")
    receipts = {}
    for line in receipt_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            receipt = json.loads(line)
            rid = receipt.get("id")
            if rid in receipts:
                raise SystemExit("Duplicate review receipt")
            receipts[rid] = receipt
    if set(receipts) != set(wanted):
        raise SystemExit("Missing or extra record-level review receipts")
    records = {}
    for line in source_bytes.decode("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("id") in wanted:
                records[row["id"]] = row
    if set(records) != set(wanted):
        raise SystemExit("Candidate records missing from source")
    events = set()
    for rid, entry in wanted.items():
        row = records[rid]
        review = receipts[rid]
        q = queue[rid]
        actual_hash = sha((row.get("text_full") or "").encode("utf-8"))
        if (actual_hash != entry["text_sha256"] or row.get("text_sha256") != actual_hash
                or q["text_sha256"] != actual_hash or review.get("text_sha256") != actual_hash):
            raise SystemExit(f"Text hash mismatch: {rid}")
        if (row.get("event_id") != entry["event_id"] or row["event_id"] in events
                or review.get("event_id") != row["event_id"]):
            raise SystemExit(f"Event mismatch or duplicate: {rid}")
        events.add(row["event_id"])
        if review.get("version") != candidate["delivery"]:
            raise SystemExit(f"Version mismatch: {rid}")
        if (not review.get("reviewer_id") or not review.get("reviewed_at")
                or review.get("review_method") not in {"human", "independent_model"}):
            raise SystemExit(f"Independent reviewer and time missing: {rid}")
        if review.get("review_method") == "independent_model" and (
                review.get("model_tier") != "flagship"
                or review.get("review_model_ids") != {p: MODELS[p][0] for p in REVIEW_TRIO}):
            raise SystemExit(f"Three approved flagship models required: {rid}")
        if not all(review.get(key) is True for key in
                   ("privacy_pass", "subject_pass", "facts_pass", "event_pass")):
            raise SystemExit(f"Record-level review incomplete: {rid}")
        flags = set(filter(None, q["automatic_flags"].split(";"))) | set(check_record(row))
        if not flags.issubset(set(review.get("closed_flags") or [])):
            raise SystemExit(f"Automatic signals not closed: {rid}")
        if flags and not review.get("closure_note_codes"):
            raise SystemExit(f"Flag closure reason codes missing: {rid}")
    out.mkdir(parents=True, exist_ok=False)
    input_path = out / "pilot50-safe.jsonl"
    with input_path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            row = records[entry["id"]]
            handle.write(json.dumps({key: row.get(key) for key in PILOT_FIELDS}, ensure_ascii=False) + "\n")
    manifest = {
        "subset_status": "record_level_review_pass",
        "review_basis": "three_flagship_model_unanimous_or_human_review",
        "whole_source_release_status": "not_approved",
        "source_version": candidate["delivery"],
        "source_file_sha256": sha(source_bytes),
        "candidate_manifest_sha256": sha(candidate_path.read_bytes()),
        "review_queue_sha256": sha(queue_path.read_bytes()),
        "receipt_file_sha256": sha(receipt_path.read_bytes()),
        "n_records": 50, "n_events": len(events),
        "model_adjudicated_completed": 0, "human_verified_completed": 0,
        "input_file": input_path.name, "input_sha256": sha(input_path.read_bytes()),
        "records": [{"id": item["id"], "event_id": item["event_id"],
                     "text_sha256": item["text_sha256"]} for item in entries],
        "later_source_revision_rule": "retain_this_frozen_source_or_relabel_changed_hashes",
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text(
        f"{sha(input_path.read_bytes())}  {input_path.name}\n"
        f"{sha(manifest_path.read_bytes())}  {manifest_path.name}\n", encoding="utf-8")
    for path in out.iterdir():
        if path.is_file():
            os.chmod(path, 0o444)
    print(json.dumps({"subset_status": manifest["subset_status"], "n_records": 50,
                      "source_version": candidate["delivery"], "input_sha256": manifest["input_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

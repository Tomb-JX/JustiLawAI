"""Compile experimental three-flagship reviews into hash-bound receipts.

Usage: python compile_flagship_review.py <manifest.json> <record_review_queue.csv>
       <review_run_dir> <new_controlled_output_dir>
Any disagreement, uncertainty, missing call or model mismatch stays unresolved.
These receipts are diagnostic and do not determine formal annotation eligibility.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

from flagship_client import MODELS, REVIEW_TRIO

ASPECTS = ("privacy", "subject", "facts", "event")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_unique(path: Path) -> dict:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            rid = item["id"]
            if rid in rows:
                raise ValueError("Duplicate model review ID")
            rows[rid] = item
    return rows


def compile_one(entry: dict, flags: list[str], reviews: dict) -> tuple[dict | None, str]:
    rid = entry["id"]
    for provider, item in reviews.items():
        if item is None:
            return None, "missing_review"
        if (item.get("status") != "valid_review"
                or item.get("provider") != provider
                or item.get("requested_model") != MODELS[provider][0]
                or item.get("returned_model") != MODELS[provider][0]
                or item.get("id") != rid
                or item.get("version") != entry["version"]
                or item.get("text_sha256") != entry["text_sha256"]
                or item.get("event_id") != entry["event_id"]
                or not item.get("response_id")):
            return None, "invalid_or_mismatched_review"
        answer = item["answer"]
        if (any(answer.get(key) != "pass" for key in ASPECTS)
                or answer.get("issue_codes")
                or answer.get("flag_dispositions") != {flag: "false_positive" for flag in flags}):
            return None, "risk_or_disagreement"
    return {
        "id": rid, "version": entry["version"],
        "text_sha256": entry["text_sha256"], "event_id": entry["event_id"],
        "reviewer_id": "three_flagship_models", "review_method": "independent_model",
        "model_tier": "flagship",
        "review_model_ids": {provider: MODELS[provider][0] for provider in REVIEW_TRIO},
        "reviewed_at": max(item["reviewed_at"] for item in reviews.values()),
        "privacy_pass": True, "subject_pass": True, "facts_pass": True, "event_pass": True,
        "closed_flags": flags,
        "closure_note_codes": ["three_flagship_unanimous_false_positive"] if flags else [],
    }, "unanimous_pass"


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    manifest_path, queue_path, run_dir, out = map(Path, argv[1:])
    repo = Path(__file__).resolve().parents[2]
    if out.resolve().is_relative_to(repo) or out.exists():
        raise SystemExit("Output must be a new controlled directory outside repository")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in manifest["entries"]}
    run = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if (run["candidate_manifest_sha256"] != sha(manifest_path.read_bytes())
            or run["queue_sha256"] != sha(queue_path.read_bytes())
            or run["delivery_file_sha256"] != manifest["delivery_file_sha256"]
            or run["models"] != {p: MODELS[p][0] for p in REVIEW_TRIO}):
        raise SystemExit("Review run does not match frozen candidate and approved models")
    with queue_path.open(encoding="utf-8-sig", newline="") as handle:
        queue = {item["id"]: item for item in csv.DictReader(handle)}
    if set(queue) != set(entries):
        raise SystemExit("Queue IDs differ from candidate")
    provider_rows = {provider: load_unique(run_dir / f"review_{provider}.jsonl")
                     for provider in REVIEW_TRIO}
    if any(set(rows) != set(entries) for rows in provider_rows.values()):
        raise SystemExit("Provider review coverage is incomplete or has extra IDs")
    receipts = []
    unresolved = []
    for rid in sorted(entries):
        flags = sorted(filter(None, queue[rid]["automatic_flags"].split(";")))
        receipt, status = compile_one(entries[rid], flags,
                                      {p: provider_rows[p].get(rid) for p in REVIEW_TRIO})
        if receipt:
            receipts.append(receipt)
        else:
            unresolved.append({"id": rid, "version": manifest["delivery"],
                               "text_sha256": entries[rid]["text_sha256"], "category": status})
    out.mkdir(parents=True, exist_ok=False)
    with (out / "review_receipts.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for item in receipts:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    with (out / "unresolved.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "version", "text_sha256", "category"])
        writer.writeheader()
        writer.writerows(unresolved)
    summary = {"reviewed_records": len(entries), "receipts_closed": len(receipts),
               "unresolved": len(unresolved), "source_version": manifest["delivery"],
               "status": "ready_for_freeze" if not unresolved else "review_pending"}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

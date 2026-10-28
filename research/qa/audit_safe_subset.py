"""Independent metadata-only audit for a record-level safe pilot subset.

Usage: python audit_safe_subset.py <candidate_manifest.json> <delivery.jsonl> <output_dir>
The output contains IDs, hashes and issue codes only. No source text is exported.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HARVEST = Path(__file__).resolve().parents[1] / "discretion" / "harvest"
sys.path.insert(0, str(HARVEST))
from deid import ALIASES, person_candidates  # noqa: E402
from r6_scan import load_whitelist, scan_record  # noqa: E402

ALLOWED_ALIASES = set(ALIASES) | {"甲"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_record(row: dict) -> list[str]:
    issues = []
    text = row.get("text_full") or ""
    facts = row.get("text_facts") or ""
    if sha(text.encode("utf-8")) != row.get("text_sha256"):
        issues.append("hash_field_mismatch")
    if row.get("deidentified") != "是" or (row.get("r6_scan") or {}).get("passed") is not True:
        issues.append("source_privacy_flag_unverified")
    hits = scan_record(row, load_whitelist())
    if any(hit.hard for hit in hits):
        issues.append("r6_hard_hit")
    if any(not hit.hard for hit in hits):
        issues.append("r6_soft_candidate")
    found, _ = person_candidates(text, "甲")
    if any(token not in ALLOWED_ALIASES and not token.startswith("人员")
           for _, _, token in found):
        issues.append("second_name_detector_signal")
    if row.get("subject_alias") != "甲" or "甲" not in facts:
        issues.append("subject_not_confirmed")
    if len("".join(facts.split())) < 30 or facts not in text:
        issues.append("facts_short_or_unlocated")
    if not (row.get("outcome") or {}).get("type"):
        issues.append("outcome_missing")
    if not row.get("province_code") or not row.get("event_id"):
        issues.append("metadata_missing")
    quality = row.get("quality") or {}
    if quality.get("ambiguous_persons") or quality.get("subject_variants"):
        issues.append("subject_ambiguity_signal")
    if quality.get("facts_contains_conclusion") or quality.get("parse_warnings"):
        issues.append("facts_or_parse_warning")
    for field in ("text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review"):
        segment = (row.get("segments") or {}).get(field)
        value = row.get(field) or ""
        if segment is None:
            if value:
                issues.append("segment_missing")
            continue
        if (not isinstance(segment, list) or len(segment) != 2
                or not all(isinstance(p, int) for p in segment)
                or not 0 <= segment[0] <= segment[1] <= len(text)
                or text[segment[0]:segment[1]] != value):
            issues.append("segment_mismatch")
    return sorted(set(issues))


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    candidate_path, source_path, out = map(Path, argv[1:])
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    source_bytes = source_path.read_bytes()
    source_sha = sha(source_bytes)
    if source_sha != candidate["delivery_file_sha256"]:
        raise SystemExit("Delivery SHA-256 differs from candidate manifest")
    wanted = {entry["id"]: entry for entry in candidate["entries"]}
    records = {}
    all_records = {}
    for line in source_bytes.decode("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rid = row.get("id")
            if rid in all_records:
                raise SystemExit("Duplicate ID in delivery")
            all_records[rid] = row
            if rid in wanted:
                records[rid] = row
    if set(records) != set(wanted):
        raise SystemExit("Candidate ID missing from delivery")
    events = Counter(row.get("event_id") for row in records.values())
    queue = []
    for rid, entry in wanted.items():
        row = records[rid]
        flags = check_record(row)
        if sha((row.get("text_full") or "").encode("utf-8")) != entry["text_sha256"]:
            flags.append("candidate_hash_mismatch")
        if row.get("event_id") != entry["event_id"] or events[row.get("event_id")] != 1:
            flags.append("event_mismatch_or_duplicate")
        queue.append({
            "id": rid, "version": candidate["delivery"], "text_sha256": entry["text_sha256"],
            "event_id": entry["event_id"], "automatic_flags": ";".join(sorted(set(flags))),
            "privacy_review": "pending", "subject_review": "pending", "facts_review": "pending",
            "event_review": "pending", "closure_status": "pending_independent_review",
        })
    out.mkdir(parents=True, exist_ok=True)
    with (out / "record_review_queue.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(queue[0]))
        writer.writeheader()
        writer.writerows(queue)
    with (out / "review_receipts.template.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for item in queue:
            handle.write(json.dumps({
                "id": item["id"], "version": item["version"],
                "text_sha256": item["text_sha256"], "event_id": item["event_id"],
                "reviewer_id": "", "review_method": "", "reviewed_at": "",
                "privacy_pass": False, "subject_pass": False,
                "facts_pass": False, "event_pass": False,
                "closed_flags": [], "closure_note_codes": [],
            }, ensure_ascii=False) + "\n")
    reserved = set(wanted) | {"W-000546", "W-000619", "W-000620", "W-000880-d205"}
    used_events = set(events)
    replacements = []
    for item in queue:
        if not item["automatic_flags"]:
            continue
        original = records[item["id"]]
        options = []
        for rid, row in all_records.items():
            if rid in reserved or not row.get("event_id") or row["event_id"] in used_events:
                continue
            if row.get("province_code") != original.get("province_code"):
                continue
            if row.get("law_version") != original.get("law_version"):
                continue
            quality = row.get("quality") or {}
            completeness = quality.get("completeness") or {}
            if not (completeness.get("has_amount") and completeness.get("has_outcome")):
                continue
            if check_record(row):
                continue
            same_source = row.get("source_type") == original.get("source_type")
            same_outcome = (row.get("outcome") or {}).get("type") == (original.get("outcome") or {}).get("type")
            options.append((not same_source, not same_outcome, rid, row))
        if options:
            different_source, different_outcome, rid, row = min(options)
            replacements.append({
                "replaces_id": item["id"], "suggested_id": rid,
                "version": candidate["delivery"],
                "text_sha256": sha(row["text_full"].encode("utf-8")),
                "event_id": row["event_id"],
                "same_source_type": not different_source,
                "same_outcome_type": not different_outcome,
                "status": "suggestion_requires_independent_review",
            })
            reserved.add(rid)
            used_events.add(row["event_id"])
    with (out / "replacement_suggestions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "replaces_id", "suggested_id", "version", "text_sha256", "event_id",
            "same_source_type", "same_outcome_type", "status"])
        writer.writeheader()
        writer.writerows(replacements)
    summary = {
        "source_version": candidate["delivery"], "source_file_sha256": source_sha,
        "whole_release_status": "not_approved", "subset_status": "review_pending",
        "n_candidates": len(queue), "n_events": len(events),
        "n_with_automatic_flags": sum(bool(item["automatic_flags"]) for item in queue),
        "flag_counts": dict(Counter(code for item in queue
                                    for code in item["automatic_flags"].split(";") if code)),
        "n_record_receipts_closed": 0,
        "n_replacement_suggestions": len(replacements),
    }
    (out / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

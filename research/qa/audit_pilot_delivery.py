"""Build a metadata-only 50-case candidate and return list from a delivery.

Usage: python audit_pilot_delivery.py <pilot50-v2.jsonl> <delivery-dir> <output-dir>
No source text or personal names are written. The output is never a gold label set.
"""
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_bytes(data):
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate record ID")
    return {row["id"]: row for row in rows}


def text_hash(row):
    return sha((row.get("text_full") or "").encode("utf-8"))


def main(args):
    if len(args) != 4:
        print(__doc__)
        return 2
    old_path, delivery, out = map(Path, args[1:])
    old_bytes = old_path.read_bytes()
    old = load_bytes(old_bytes)
    source = delivery / "admin_cases.schema-1.0.0.jsonl"
    source_bytes = source.read_bytes()
    current = load_bytes(source_bytes)
    releases = sorted(path for path in delivery.parent.iterdir()
                      if path.is_dir() and path.name < delivery.name
                      and (path / source.name).exists())
    prior_path = releases[-1] / source.name if releases else delivery / "_no_prior_release"
    prior_bytes = prior_path.read_bytes() if prior_path.exists() else None
    prior = load_bytes(prior_bytes) if prior_bytes else {}
    version = delivery.name
    returns = []
    candidate = []
    events = {}
    for rid, previous in old.items():
        row = current.get(rid)
        if row is None:
            returns.append({"id": rid, "category": "missing_in_delivery", "version": version,
                            "text_sha256": "", "closure": "replace_and_recheck_event"})
            continue
        h = text_hash(row)
        event = row.get("event_id")
        if not event:
            returns.append({"id": rid, "category": "missing_event_id", "version": version,
                            "text_sha256": h, "closure": "source_event_link_verified"})
        elif event in events:
            returns.append({"id": rid, "category": "duplicate_event", "version": version,
                            "text_sha256": h, "closure": "one_case_per_event"})
        events[event] = rid
        if previous.get("event_id") != event:
            returns.append({"id": rid, "category": "event_id_changed", "version": version,
                            "text_sha256": h, "closure": "event_link_manual_review"})
        if text_hash(previous) != h:
            returns.append({"id": rid, "category": "text_changed_since_pilot50_v2", "version": version,
                            "text_sha256": h, "closure": "fresh_independent_model_annotation"})
        if row.get("text_sha256") != h:
            returns.append({"id": rid, "category": "text_hash_field_mismatch", "version": version,
                            "text_sha256": h, "closure": "source_hash_corrected"})
        scan = row.get("r6_scan") or {}
        if not row.get("deidentified") or scan.get("passed") is not True:
            returns.append({"id": rid, "category": "privacy_scan_unverified", "version": version,
                            "text_sha256": h, "closure": "independent_privacy_review"})
        candidate.append({"id": rid, "event_id": event, "version": version,
                          "text_sha256": h, "law_version": row.get("law_version"),
                          "source_type": row.get("source_type")})
    # Prior human report identified a de-identification risk in this ID family.
    for rid in ("W-000156-d17", "W-000156-d23", "W-000156-d55"):
        if rid in current:
            returns.append({"id": rid, "category": "prior_privacy_or_subject_alignment",
                            "version": version, "text_sha256": text_hash(current[rid]),
                            "closure": "independent_privacy_and_subject_review"})
    for rid in ("W-000546", "W-000619", "W-000620", "W-000880-d205"):
        if rid in current and rid in prior:
            unchanged = text_hash(current[rid]) == text_hash(prior[rid])
            returns.append({
                "id": rid,
                "category": "prior_privacy_hash_unchanged" if unchanged else "privacy_revision_needs_recheck",
                "version": version, "text_sha256": text_hash(current[rid]),
                "closure": "independent_privacy_review_same_hash",
            })
    if sha(source.read_bytes()) != sha(source_bytes):
        raise SystemExit("Delivery changed during candidate audit; retry after release stabilizes")
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "status": "candidate_not_frozen", "gold_labels": 0,
        "model_adjudicated_completed": 0, "human_verified_completed": 0,
        "planned_label_origin": "model-adjudicated", "planned_human_review": False,
        "delivery": version,
        "delivery_file_sha256": sha(source_bytes), "old_input_sha256": sha(old_bytes),
        "prior_delivery_file_sha256": sha(prior_bytes) if prior_bytes else None,
        "prior_delivery": prior_path.parent.name if prior_path.exists() else None,
        "n_candidate": len(candidate), "n_events": len({r["event_id"] for r in candidate}),
        "entries": candidate,
        "freeze_requires": [
            "source_release_and_independent_privacy_review_pass",
            "all_return_items_closed_by_id_and_text_hash",
            "one_case_per_event",
            "guide_schema_conflicts_recorded_and_versioned",
            "heterogeneous_models_A_B_C_receive_same_immutable_input",
        ],
    }
    (out / "candidate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "return_list.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "category", "version", "text_sha256", "closure"])
        writer.writeheader()
        writer.writerows(sorted(returns, key=lambda r: (r["id"], r["category"])))
    summary = {"status": manifest["status"], "n_candidate": len(candidate),
               "n_events": manifest["n_events"], "return_categories": dict(Counter(r["category"] for r in returns))}
    (out / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

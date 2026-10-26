"""Read-only crash-recovery and cost audit; never discards a torn tail or retries HTTP."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from durable_calls import read_rows


def audit(run: Path):
    paths = [run / name for name in ("attempts.jsonl", "raws.jsonl", "manifest.json", "execution-manifest.json")]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}
    events, raws = read_rows(paths[0]), read_rows(paths[1])
    submitted, completed = {}, {}
    issues = []
    for e in events:
        if e["event"] == "submitted":
            if e["attempt_id"] in submitted:
                issues.append("duplicate_attempt_id")
            submitted[e["attempt_id"]] = e
        elif e["event"] == "finished":
            if e["attempt_id"] in completed:
                issues.append("duplicate_completion_id")
            completed[e["attempt_id"]] = e
    raw_ids = {r["attempt_id"] for r in raws}
    unknown = sorted(submitted.keys() - completed.keys())
    issues += ["completion_without_raw:" + key for key in completed if key not in raw_ids]
    issues += ["completion_without_submission:" + key for key in completed if key not in submitted]
    costs = sum(completed[key]["charged"] if key in completed else row["reservation"] for key, row in submitted.items())
    return {"version": "run-audit-1", "attempts": len(submitted), "raw_responses": len(raws),
            "estimated_charged_or_reserved": costs, "unknown_attempts": unknown,
            "raw_recoverable_without_new_call": sorted(raw_ids & set(unknown)),
            "by_provider": dict(Counter(e["provider"] for e in submitted.values())),
            "issues": issues, "source_hashes": hashes, "automatic_resubmission": False,
            "remote_billing_confirmed": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    a = p.parse_args()
    print(json.dumps(audit(a.run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Freeze reviewed parallel S1 orders for the leak-screened L5 cohort."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pool", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--runner", type=Path, required=True)
    a = p.parse_args()
    pool = json.loads((a.pool / "MANIFEST.json").read_text("utf-8"))
    pilot = json.loads((a.root / "pilot5" / "seg-run" / "manifest.json").read_text("utf-8"))["ids"]
    eligible = {r["id"] for r in pool["records"] if not r["reuse_output_id"]}
    pilot_eligible = [rid for rid in pilot if rid in eligible]
    remaining = [rid for rid in json.loads((a.pool / "missing-ids.json").read_text("utf-8")) if rid not in pilot_eligible]
    names = []
    for start in range(0, len(remaining), 12):
        ids = remaining[start:start + 12]
        name = f"safe-batch{len(names) + 1:02d}"
        names.append(name)
        folder = a.root / name
        folder.mkdir(exist_ok=False)
        (folder / "ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n", "utf-8")
        run = folder / "seg-run"
        cmd = [sys.executable, "-B", str(a.runner), "--batch", str(a.root / "input" / "records.jsonl"),
               "--out", str(run), "--ids", str(folder / "ids.json"), "--clause-refine"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        manifest = json.loads((run / "manifest.json").read_text("utf-8"))
        plan_hash = digest(manifest)
        if json.loads(result.stdout)["plan_hash"] != plan_hash or manifest["ids"] != ids:
            raise ValueError(f"plan mismatch: {name}")
        order = {"free_replay_pass": True, "max_calls": len(ids) * 2,
                 "review_record": "user-authorized-latest-quality-L5-no-old299-2026-10-18",
                 "provider": "deepseek", "plan_hash": plan_hash, "max_input_bytes": 50000,
                 "stage": "smoke12", "cap": 0.7, "providers": {"S1": "deepseek"},
                 "acceptance": {"primary": "S3-error-and-L5-facts-view-eligibility", "records": len(ids)},
                 "ids": ids, "engine_ack": "L5-teacher-input-after-S3-and-answer-leak-guard",
                 "executor_review": "source-screened-clean2883-exact-hash-frozen-12-record-shard",
                 "budget_scope": {"path": str(a.root / "shared-budget"), "max_calls": 744, "cap": 15.0}}
        (folder / "approved-order.json").write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n", "utf-8")
    plan = {"version": "l5-quality-batch-plan-2", "pool": str(a.pool), "run_ids": remaining,
            "run_batches": names, "pilot_ids": pilot_eligible, "total_missing": len(eligible),
            "shared_cap_yuan": 15.0, "max_workers": 4}
    (a.root / "batch-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"selected": pool["selected"], "reused": pool["reused"],
                      "pilot_reused": len(pilot_eligible), "new_calls": len(remaining),
                      "batches": len(names)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Verify all paid and reused S1 outputs for a frozen latest-quality pool."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from durable_calls import read_rows


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--pool", type=Path, help="pool MANIFEST.json to scope the aggregate (default: root MANIFEST.json)")
    p.add_argument("--pool-scoped", action="store_true",
                   help="v3b cohort: tolerate out-of-pool pilot/reused rows and partial safe-batch snapshots; "
                        "global paid==missing still enforces completeness")
    a = p.parse_args()
    pool = json.loads((a.pool or a.root / "MANIFEST.json").read_text("utf-8"))
    plan = json.loads((a.root / "batch-plan.json").read_text("utf-8"))
    expected = [r["id"] for r in pool["records"]]
    missing = {r["id"] for r in pool["records"] if not r["reuse_output_id"]}
    reused = {r["id"]: r for r in read_rows(a.root / "input" / "reused-outputs.jsonl")}
    skipped_reused: list[str] = []
    if a.pool_scoped:
        in_pool = set(expected)
        skipped_reused = sorted(set(reused) - in_pool)
        reused = {k: v for k, v in reused.items() if k in in_pool}
    if len(reused) != pool["reused"] or set(reused) != set(expected) - missing:
        raise ValueError("reused outputs incomplete")
    paid, versions, batches = {}, set(), []
    skipped_paid: list[str] = []
    for name in ["pilot5", *plan["run_batches"]]:
        run = a.root / name / "seg-run"
        manifest = json.loads((run / "manifest.json").read_text("utf-8"))
        versions.add((manifest["version"], manifest["semantic_prompt_base"], manifest["clause_refine"],
                      manifest["source_sha256"], json.dumps(manifest["implementation"], sort_keys=True)))
        rows = list(read_rows(run / "outputs.jsonl"))
        if a.pool_scoped:
            if not {x["id"] for x in rows} <= set(manifest["ids"]):
                raise ValueError(f"extra outputs: {name}")
            out_of_pool = [x["id"] for x in rows if x["id"] not in missing]
            rows = [x for x in rows if x["id"] in missing]
            skipped_paid.extend(out_of_pool)
        elif len(rows) != len(manifest["ids"]) or {x["id"] for x in rows} != set(manifest["ids"]):
            raise ValueError(f"incomplete run: {name}")
        for row in rows:
            rid = row["id"]
            if (rid in paid or not row.get("ok") or row.get("validation_errors")
                    or row.get("request_hash") != manifest["request_hashes"][rid]
                    or row.get("prompt_version") != manifest["version"]):
                raise ValueError(f"invalid paid output: {rid}")
            paid[rid] = row
        batches.append({"name": name, "records": len(rows), "manifest_sha256": sha(run / "manifest.json"),
                        "outputs_sha256": sha(run / "outputs.jsonl")})
    if len(versions) != 1 or set(paid) != missing or set(paid) & set(reused):
        raise ValueError("mixed implementation or incorrect paid/reused partition")
    version, base, clause, source, _ = next(iter(versions))
    if source != sha(a.root / "input" / "records.jsonl"):
        raise ValueError("source input changed")
    combined = a.root / "combined"
    combined.mkdir(exist_ok=False)
    out = combined / "outputs.jsonl"
    outputs = {**paid, **reused}
    out.write_text("".join(json.dumps(outputs[rid], ensure_ascii=False) + "\n" for rid in expected), "utf-8")
    ledger = list(read_rows(a.root / "shared-budget" / "ledger.jsonl"))
    reserved = {x["key"]: x for x in ledger if x["event"] == "reserved"}
    settled = {x["key"]: x["charged"] for x in ledger if x["event"] == "settled"}
    legacy_unsettled = sorted(set(reserved) - set(settled))
    if legacy_unsettled:
        if not a.pool_scoped or not (a.root / "executor-summary.json").exists():
            raise ValueError("unsettled call")
    provenance = {"version": "l5-quality-s1-combined-1", "pool_sha256": sha(a.pool or a.root / "MANIFEST.json"),
                  "input_sha256": source, "records": len(outputs), "paid_records": len(paid),
                  "reused_records": len(reused), "prompt_version": version,
                  "semantic_prompt_base": base, "clause_refine": clause, "batches": batches,
                  "outputs_sha256": sha(out), "paid_calls": len(settled),
                  "settled_cost_yuan": round(sum(settled.values()), 6),
                  "warning": "source-screened candidate; S3 and teacher-view checks still required"}
    if a.pool_scoped:
        provenance["pool_scoping"] = {"out_of_pool_paid_rows_skipped": skipped_paid,
                                      "out_of_pool_reused_rows_skipped": skipped_reused,
                                      "legacy_unsettled_keys": legacy_unsettled}
    (combined / "PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: provenance[k] for k in ("records", "paid_records", "reused_records", "paid_calls", "settled_cost_yuan")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

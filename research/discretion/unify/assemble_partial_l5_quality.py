"""Safely assemble completed S1 outputs after a provider balance interruption."""
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
    p.add_argument("--pool", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error("output already exists")
    cohort = json.loads((a.pool / "MANIFEST.json").read_text("utf-8"))
    eligible = {r["id"] for r in cohort["records"]}
    plan = json.loads((a.root / "batch-plan.json").read_text("utf-8"))
    reused = {r["id"]: r for r in read_rows(a.root / "input" / "reused-outputs.jsonl")
              if r["id"] in eligible}
    paid, versions, inspected = {}, set(), []
    for name in ["pilot5", *plan["run_batches"]]:
        run = a.root / name / "seg-run"
        manifest = json.loads((run / "manifest.json").read_text("utf-8"))
        versions.add((manifest["version"], manifest["semantic_prompt_base"], manifest["clause_refine"],
                      manifest["source_sha256"], json.dumps(manifest["implementation"], sort_keys=True)))
        path = run / "outputs.jsonl"
        rows = list(read_rows(path)) if path.exists() else []
        if [r["id"] for r in rows] != manifest["ids"][:len(rows)]:
            raise ValueError(f"non-prefix partial output: {name}")
        for row in rows:
            rid = row["id"]
            if (not row.get("ok") or row.get("validation_errors")
                    or row.get("request_hash") != manifest["request_hashes"][rid]
                    or row.get("prompt_version") != manifest["version"]):
                raise ValueError(f"invalid output: {rid}")
            if rid in eligible:
                if rid in paid:
                    raise ValueError(f"duplicate output: {rid}")
                paid[rid] = row
        inspected.append({"batch": name, "completed": len(rows), "planned": len(manifest["ids"])})
    if len(versions) != 1 or set(reused) & set(paid):
        raise ValueError("mixed snapshot or duplicate reuse")
    version, base, clause, source, _ = next(iter(versions))
    if source != sha(a.root / "input" / "records.jsonl") or len(reused) != cohort["reused"]:
        raise ValueError("input/reuse mismatch")
    outputs = {**reused, **paid}
    ordered = [outputs[r["id"]] for r in cohort["records"] if r["id"] in outputs]
    a.out.mkdir(parents=True)
    out = a.out / "outputs.jsonl"
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered), "utf-8")
    ledger = list(read_rows(a.root / "shared-budget" / "ledger.jsonl"))
    settled = [r for r in ledger if r["event"] == "settled"]
    manifest = {"version": "l5-quality-partial-1", "pool_sha256": sha(a.pool / "MANIFEST.json"),
                "source_sha256": source, "outputs_sha256": sha(out), "prompt_version": version,
                "semantic_prompt_base": base, "clause_refine": clause, "selected": cohort["selected"],
                "complete": len(ordered), "reused": len(reused), "paid_in_cohort": len(paid),
                "pending": cohort["selected"] - len(ordered), "settled_calls_total": len(settled),
                "settled_cost_yuan": round(sum(r["charged"] for r in settled), 6),
                "inspected": inspected, "interruption": "provider HTTP 402 insufficient balance",
                "labels_generated": False}
    (a.out / "PROVENANCE.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in ("selected", "complete", "reused", "paid_in_cohort", "pending", "settled_calls_total", "settled_cost_yuan")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

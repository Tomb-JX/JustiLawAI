"""Verify and combine frozen same-version S1 subruns for one candidate cohort."""
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
    a = p.parse_args()
    cohort = json.loads((a.root / "cohort.json").read_text("utf-8"))
    expected = cohort["ids"]
    if len(expected) != len(set(expected)) or len(expected) != 57:
        raise ValueError("unexpected cohort IDs")
    names = ("pilot5", "batch1", "batch2", "batch3", "batch4", "batch5")
    outputs, versions, batches = {}, set(), []
    for name in names:
        run = a.root / name / "seg-run"
        manifest = json.loads((run / "manifest.json").read_text("utf-8"))
        versions.add((manifest["version"], manifest["semantic_prompt_base"], manifest["clause_refine"],
                      manifest["source_sha256"], json.dumps(manifest["implementation"], sort_keys=True)))
        current = list(read_rows(run / "outputs.jsonl"))
        if len(current) != len(manifest["ids"]) or {x["id"] for x in current} != set(manifest["ids"]):
            raise ValueError(f"missing or extra outputs in {name}")
        for row in current:
            rid = row["id"]
            if (rid in outputs or not row.get("ok") or row.get("validation_errors")
                    or row.get("request_hash") != manifest["request_hashes"][rid]
                    or row.get("prompt_version") != manifest["version"]):
                raise ValueError(f"invalid or duplicate output: {rid}")
            outputs[rid] = row
        batches.append({"name": name, "records": len(current), "manifest_sha256": sha(run / "manifest.json"),
                        "outputs_sha256": sha(run / "outputs.jsonl")})
    if len(versions) != 1 or set(outputs) != set(expected):
        raise ValueError("mixed implementation or incomplete candidate cohort")
    version, base, clause, source_hash, _ = next(iter(versions))
    if source_hash != cohort["source_sha256"]:
        raise ValueError("cohort source mismatch")
    out_dir = a.root / "combined"
    out_dir.mkdir(exist_ok=False)
    out_path = out_dir / "outputs.jsonl"
    out_path.write_text("".join(json.dumps(outputs[rid], ensure_ascii=False) + "\n" for rid in expected), "utf-8")
    ledger = list(read_rows(a.root / "shared-budget" / "ledger.jsonl"))
    reserved = {row["key"] for row in ledger if row["event"] == "reserved"}
    settled = {row["key"]: row["charged"] for row in ledger if row["event"] == "settled"}
    if reserved != set(settled):
        raise ValueError("unsettled paid call")
    provenance = {"version": "candidate-same-version-1", "cohort_sha256": sha(a.root / "cohort.json"),
                  "records": len(outputs), "prompt_version": version, "semantic_prompt_base": base,
                  "clause_refine": clause, "source_sha256": source_hash, "batches": batches,
                  "outputs_sha256": sha(out_path), "paid_calls": len(settled),
                  "settled_cost_yuan": round(sum(settled.values()), 6),
                  "warning": "screened post-hoc candidate denominator; not fixed299 population gate"}
    (out_dir / "PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(provenance, ensure_ascii=False))


if __name__ == "__main__":
    main()

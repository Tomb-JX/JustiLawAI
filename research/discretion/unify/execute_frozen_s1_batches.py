"""Execute reviewed S1 subruns concurrently against one shared budget scope."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


HERE = Path(__file__).resolve().parent


def run_one(root: Path, batch: Path, name: str) -> dict:
    folder = root / name
    run = folder / "seg-run"
    cmd = [sys.executable, "-B", str(HERE / "run_seg.py"), "--batch", str(batch),
           "--out", str(run), "--ids", str(folder / "ids.json"), "--clause-refine",
           "--execute", "--order", str(folder / "approved-order.json")]
    result = subprocess.run(cmd, cwd=HERE.parents[2], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode == 0:
        s3 = [sys.executable, "-B", str(HERE / "run_s3.py"), "--batch", str(batch),
              "--run", str(run), "--out", "s3"]
        checked = subprocess.run(s3, cwd=HERE.parents[2], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
    else:
        checked = None
    log = {"batch": name, "s1_exit": result.returncode, "s1_output": (result.stdout + result.stderr)[-3000:],
           "s3_exit": checked.returncode if checked else None,
           "s3_output": (checked.stdout + checked.stderr)[-3000:] if checked else None}
    (folder / "executor-result.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return log


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    if not 1 <= a.workers <= 8:
        p.error("workers must be 1..8")
    plan = json.loads((a.root / "batch-plan.json").read_text("utf-8"))
    names = plan["run_batches"]
    if len(names) != len(set(names)):
        raise ValueError("duplicate batch names")
    manifests = [json.loads((a.root / name / "seg-run" / "manifest.json").read_text("utf-8")) for name in names]
    fixed = {(m["version"], m["semantic_prompt_base"], m["clause_refine"], m["source_sha256"],
              json.dumps(m["implementation"], sort_keys=True)) for m in manifests}
    ids = [rid for m in manifests for rid in m["ids"]]
    if len(fixed) != 1 or ids != plan["run_ids"] or any(len(m["ids"]) > 12 for m in manifests):
        raise ValueError("mixed implementation or incomplete plan")
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        tasks = {pool.submit(run_one, a.root, a.batch, name): name for name in names}
        for future in as_completed(tasks):
            row = future.result()
            results.append(row)
            print(json.dumps({"batch": row["batch"], "s1_exit": row["s1_exit"],
                              "s3_exit": row["s3_exit"]}, ensure_ascii=False), flush=True)
            if row["s1_exit"] or row["s3_exit"]:
                for pending in tasks:
                    pending.cancel()
                raise RuntimeError(f"batch failed: {row['batch']}")
    (a.root / "executor-summary.json").write_text(json.dumps({"workers": a.workers,
             "completed": len(results), "batches": sorted(row["batch"] for row in results)}, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()

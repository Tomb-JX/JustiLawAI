"""Describe fixed-batch S3 errors by conservative source suitability, without changing its denominator."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from durable_calls import read_rows
from gold_candidate_audit import reasons


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("unified", "parsed", "findings", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    unified = {r["id"]: r for r in read_rows(a.unified)}
    parsed = {r["id"]: r for r in read_rows(a.parsed)}
    counts, errors, rows = Counter(), Counter(), []
    for finding in read_rows(a.findings):
        rid = finding["id"]
        flags = reasons(unified[rid], parsed.get(rid))
        group = "candidate_screen_pass" if not flags else "candidate_screen_fail"
        counts[group] += 1
        if finding["status"] == "error":
            errors[group] += 1
        rows.append({"id": rid, "group": group, "source_flags": flags,
                     "s3_status": finding["status"]})
    report = {"fixed_denominator": len(rows), "fixed_errors": sum(errors.values()),
              "screen_counts": dict(counts), "screen_errors": dict(errors),
              "warning": "post-hoc descriptive stratification; not a replacement S3 gate or gold label",
              "records": rows}
    with a.out.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

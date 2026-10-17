"""S3 运行器（seg-v2 句表分区语义）：对一份 S1 run 的成功输出跑校验注册表。

用法：
  python research/discretion/unify/run_s3.py --batch <unified_raw/records.jsonl> \
      --run <s1_runs/<run_id>> [--out 子目录名]
产物（<s1_run>/<out>/）：findings.jsonl、summary.json。
seg-v2 下引文消歧随引文接口移除（分区坐标来自句表，无需定位消歧）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import OffsetIndex  # noqa: E402
from s3 import run_checks, zone_spans  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="unified_raw records.jsonl")
    ap.add_argument("--run", required=True, help="s1_runs/<run_id> 目录")
    ap.add_argument("--out", default="s3", help="run 目录下的输出子目录名")
    a = ap.parse_args()

    records = {r["id"]: r for r in (json.loads(l) for l in open(a.batch, encoding="utf-8"))}
    outputs = [json.loads(l) for l in open(Path(a.run) / "outputs.jsonl", encoding="utf-8")]
    outputs = [o for o in outputs if o.get("ok")]
    s3_dir = Path(a.run) / a.out
    s3_dir.mkdir(exist_ok=True)

    edits_path = Path(a.batch).parent / "edits.rle.jsonl"
    edits = {}
    for l in open(edits_path, encoding="utf-8"):
        e = json.loads(l)
        edits[e["id"]] = e

    results = []
    for o in outputs:
        rec = records.get(o["id"])
        if rec is None or o["id"] not in edits:
            continue
        sentences = rec.get("sentences") or []
        index = OffsetIndex(edits[o["id"]])
        spans = zone_spans(o["output"], sentences, index)
        ctx = {"record": rec, "output": o["output"], "sentences": sentences, "spans": spans}
        findings = run_checks(ctx)
        status = "error" if any(f.severity == "error" for f in findings) else \
                 ("warn" if findings else "pass")
        results.append({"id": o["id"], "status": status, "form": rec["form"],
                        "findings": [f.as_dict() for f in findings],
                        "spans": {typ: [[cs, ce, os_, oe] for cs, ce, os_, oe in lst]
                                  for typ, lst in spans.items()}})

    with open(s3_dir / "findings.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_check: Counter = Counter()
    status_c: Counter = Counter()
    form_err: Counter = Counter()
    for r in results:
        status_c[r["status"]] += 1
        if r["status"] == "error":
            form_err[r["form"]] += 1
        for fd in r["findings"]:
            by_check[(fd["check"], fd["severity"])] += 1
    summary = {
        "run": a.run, "n": len(results),
        "status": dict(status_c),
        "hard_failure_rate": round(status_c.get("error", 0) / len(results), 4) if results else 0,
        "by_check": {f"{c}|{s}": n for (c, s), n in by_check.most_common()},
        "errors_by_form": dict(form_err),
    }
    (s3_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

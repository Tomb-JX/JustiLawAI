"""Seal F5 (the one-shot release test of binding v2) and put the rest of the fresh records into U.

Input: teacher inputs from S1 runs on records no earlier batch ever processed. Every record
that shares a source or a near-duplicate event (facts 3-gram similarity) with dev, H3, T4 or
U is dropped (`prepare_relation_model_batch_v2.prepare`), one record is kept per event, and a
seeded random draw seals F5. F5 answers are produced later by double-blind model review and
adjudication; the main session reads only aggregate scores, once, after v2 is frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from prepare_relation_model_batch_v2 import prepare

SEED = 20261028


def write(out: Path, rows: list[dict], manifest: dict) -> None:
    out.mkdir(parents=True)
    path = out / "inputs.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    manifest["inputs_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--teacher", type=Path, required=True)
    ap.add_argument("--originals", type=Path, required=True)
    ap.add_argument("--protect", type=Path, action="append", required=True)
    ap.add_argument("--f5-size", type=int, default=300)
    ap.add_argument("--f5-out", type=Path, required=True)
    ap.add_argument("--u-out", type=Path, required=True)
    args = ap.parse_args()
    if args.f5_out.exists() or args.u_out.exists():
        ap.error("output_already_exists")
    first, *rest = args.protect
    rows, base = prepare(args.teacher, args.originals, first, rest, size=None, splits={"pool": 0},
                         source_run="f5-prep-20261028")
    rows = sorted(rows, key=lambda r: r["id"])
    random.Random(SEED).shuffle(rows)
    n = min(args.f5_size, len(rows))
    f5, extra = rows[:n], rows[n:]
    for r in f5:
        r["split"] = "sealed_test_f5"
    for r in extra:
        r["split"], r["u_source"] = "u_pool", "f5-prep-20261028"
    common = {"seed": SEED, "protected": [str(p) for p in args.protect],
              "protected_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.protect},
              "teacher_sha256": hashlib.sha256(args.teacher.read_bytes()).hexdigest(),
              "funnel": base["funnel"], "event_clusters": base["event_clusters"]}
    write(args.f5_out, f5, {"version": "f5-sealed-1", **common, "records": len(f5), "sealed": True,
                            "rule": "F5 answers come from double-blind model review plus adjudication by a separate "
                                    "reviewer; the main session reads only aggregate scores, once, after v2 is frozen",
                            "flags": {k: sum(r["flags"][k] for r in f5) for k in f5[0]["flags"]} if f5 else {}})
    write(args.u_out, extra, {"version": "u-pool-extra-1", **common, "records": len(extra),
                              "purpose": "unlabelled pool extension; never an evaluation set"})
    print(json.dumps({"f5": len(f5), "u_extra": len(extra), "funnel": base["funnel"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

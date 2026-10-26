"""Strict teacher inputs from the lake-text S1 runs, for a fresh sealed holdout.

The lake queue keys records by S1 id while edits and originals are keyed by
source id per (channel, batch). This re-keys them, then applies the unchanged
`load_work` gates (replay, S3 errors, answer leakage). Leaking records are
quarantined, never view-remediated, so no new remediation rule touches the holdout.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from run_elements import load_work


def assemble(queue: Path, data: Path, out: Path) -> Path:
    records = list(rows(queue / "records.jsonl"))
    by_batch: dict[tuple, dict] = {}
    for key in {(r["channel"], r["source_batch"]) for r in records}:
        ch, b = key
        by_batch[key] = {
            "edits": {e["id"]: e for e in rows(data / f"unified_raw_refresh/20261018-party/{ch}/{b}/edits.rle.jsonl")},
            "parsed": {p["id"]: p for p in rows(data / f"parsed_refresh/20261018/{ch}/{b}/records.jsonl")}}
    out.mkdir(parents=True, exist_ok=False)
    with (out / "records.jsonl").open("w", encoding="utf-8") as fr, \
            (out / "edits.rle.jsonl").open("w", encoding="utf-8") as fe, \
            (out / "originals.jsonl").open("w", encoding="utf-8") as fo:
        for r in records:
            src = by_batch[(r["channel"], r["source_batch"])]
            edit = dict(src["edits"][r["source_id"]], id=r["id"])
            fr.write(json.dumps(r, ensure_ascii=False) + "\n")
            fe.write(json.dumps(edit, ensure_ascii=False) + "\n")
            fo.write(json.dumps({"id": r["id"], "source_id": r["source_id"],
                                 "text_full": src["parsed"][r["source_id"]]["text_full"]}, ensure_ascii=False) + "\n")
    return out / "records.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("queue", "data", "out"):
        ap.add_argument("--" + name, type=Path, required=True)
    ap.add_argument("--run", type=Path, action="append", required=True, help="S1 run dirs; later ones fill gaps")
    args = ap.parse_args()
    unified = assemble(args.queue, args.data, args.out / "input")
    seen, teacher, originals, rejected = set(), [], [], Counter()
    for run in args.run:
        work, rej = load_work(run, unified, args.out / "input" / "originals.jsonl")
        rejected.update(x["reason"].split(":")[0] for x in rej if x["id"] not in seen)
        for rid, rec, inp in work:
            if rid in seen:
                continue
            seen.add(rid)
            teacher.append({"id": rid, **inp, "label_provenance": "unlabeled-S1-teacher-input"})
            originals.append({"id": rid, "text_full": rec["_text_full"]})
    (args.out / "teacher-inputs.jsonl").write_text(
        "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in teacher), "utf-8")
    (args.out / "originals.jsonl").write_text(
        "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in originals), "utf-8")
    summary = {"teacher_inputs": len(teacher), "rejected_reasons": dict(rejected),
               "runs": [str(r) for r in args.run], "remediation": "none (strict load_work gates)"}
    (args.out / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

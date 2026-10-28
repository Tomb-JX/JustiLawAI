"""Freeze the unlabelled pool U for weak supervision from every existing S1 teacher-input set.

Sources are taken in order; each one excludes the protected evaluation sets (dev pool, H3,
T4, and any sealed set given) plus everything U already holds, by source hash and by facts
3-gram similarity (`prepare_relation_model_batch_v2.prepare`), so U never shares an event
with an evaluation set and holds one record per event. No labels are attached: U carries
only text, target and views.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from prepare_relation_model_batch_v2 import prepare


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", nargs=3, action="append", required=True, metavar=("NAME", "TEACHER", "ORIGINALS"))
    ap.add_argument("--protect", type=Path, action="append", required=True,
                    help="inputs.jsonl of an evaluation set U must not overlap")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    first, *rest = args.protect
    taken: list[Path] = []
    pool, funnels = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, teacher, originals in args.source:
            rows, manifest = prepare(Path(teacher), Path(originals), first, [*rest, *taken],
                                     size=None, splits={"u_pool": 0}, source_run=name)
            for r in rows:
                r["u_source"] = name
            part = Path(tmp) / f"{name}.jsonl"
            part.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
            taken.append(part)
            pool += rows
            funnels[name] = {"funnel": manifest["funnel"], "event_clusters": manifest["event_clusters"],
                             "selected": len(rows)}
    args.out.mkdir(parents=True)
    path = args.out / "inputs.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pool), "utf-8")
    manifest = {"version": "u-pool-1", "purpose": "unlabelled pool for weak supervision; never an evaluation set",
                "protected": [str(p) for p in args.protect],
                "protected_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.protect},
                "sources": funnels, "records": len(pool),
                "flags": {k: sum(r["flags"][k] for r in pool) for k in pool[0]["flags"]} if pool else {},
                "inputs_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

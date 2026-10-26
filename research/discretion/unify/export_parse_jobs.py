"""Export label-free parse jobs: every visible facts span of the given batches.

A job is keyed by the SHA256 of its exact text, so the external parser cache is
content-addressed and reusable across batches and reruns. No labels, targets or
quantities leave this step; the parser environment only ever sees text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from audit_supply_replay import rows
from minimal_amount_closure import load_records
from supply_packet import build_packet


def jobs_from(text_full: str, record: dict, rid: str):
    packet = build_packet(text_full, record, record_id=rid)
    for view in packet["visible_spans"]:
        if view["zone"] == "facts" and view["quote"].strip():
            yield hashlib.sha256(view["quote"].encode("utf-8")).hexdigest(), view["quote"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=Path, action="append", default=[])
    ap.add_argument("--silver", nargs=3, type=Path, metavar=("TEACHER", "ORIGINALS", "SILVER"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    seen: dict[str, str] = {}
    for batch in args.batch:
        for r in rows(batch / "inputs.jsonl"):
            seen.update(jobs_from(r["text_full"], r, r["id"]))
    if args.silver:
        teacher, originals, silver = args.silver
        texts = {r["id"]: r["text_full"] for r in rows(originals)}
        for rid, inp, _, _ in load_records(teacher, originals, silver, {"train", "valid", "test"}):
            seen.update(jobs_from(texts[rid], inp, rid))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps({"key": k, "text": t}, ensure_ascii=False) + "\n"
                                for k, t in sorted(seen.items())), "utf-8")
    print(json.dumps({"jobs": len(seen), "chars": sum(len(t) for t in seen.values())}))


if __name__ == "__main__":
    main()

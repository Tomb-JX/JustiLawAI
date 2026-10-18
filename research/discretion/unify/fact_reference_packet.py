"""Create an unlabeled, source-hashed packet for independent fact-role review."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from durable_calls import read_rows
from fact_spans import candidate_fact_clauses


def make_packet(unified: Path, reference: Path, out: Path):
    rows = {r["id"]: r for r in read_rows(unified)}
    source = json.loads(reference.read_text("utf-8"))
    with out.open("x", encoding="utf-8", newline="\n") as f:
        for item in source["records"]:
            rec = rows[item["id"]]
            source_hash = hashlib.sha256(rec["cleaned_text"].encode()).hexdigest()
            if source_hash != item["cleaned_sha256"]:
                raise ValueError(f"source_changed:{item['id']}")
            candidates = candidate_fact_clauses(rec["cleaned_text"], rec["sentences"])
            labeled = {cid for ids in item["roles"].values() for cid in ids}
            target_sentences = {c["sentence"] for c in candidates if c["id"] in labeled}
            visible = [c for c in candidates if c["sentence"] in target_sentences]
            packet = {"id": item["id"], "scope": item["scope"],
                      "cleaned_sha256": source_hash,
                      "instruction": "逐子句填 behavior_core/context_time/other_case_fact/heading/legal_conclusion/decision/evidence/ambiguous；不确定说明原因。",
                      "clauses": [{**c, "review_role": None, "review_note": None} for c in visible],
                      "reviewer": None, "reviewed_at": None}
            f.write(json.dumps(packet, ensure_ascii=False) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--unified", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    make_packet(a.unified, a.reference, a.out)


if __name__ == "__main__":
    main()

"""Freeze source-page-disjoint fact-role review material without model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from durable_calls import read_rows
from fact_spans import candidate_fact_clauses

SEED = 20261018


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--unified", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    records = {r["id"]: r for r in read_rows(a.unified)}
    audit = [json.loads(line) for line in a.audit.read_text("utf-8").splitlines()]
    excluded_ids = {r["id"] for r in json.loads(a.reference.read_text("utf-8"))["records"]}
    excluded_pages = {row["source_page"] for row in audit if row["id"] in excluded_ids}
    rng = random.Random(SEED)
    selected, used_pages = [], set(excluded_pages)
    for stratum, target in (("conservative_candidate", 50), ("hard_negative", 20)):
        pool = []
        for item in audit:
            rec = records[item["id"]]
            if item["source_page"] in used_pages or item["id"] in excluded_ids:
                continue
            if stratum == "conservative_candidate" and item["candidate"]:
                pool.append(item)
            elif (stratum == "hard_negative" and not item["candidate"]
                  and rec["form"].startswith("叙述式") and rec["prefilter"]["release"]
                  and candidate_fact_clauses(rec["cleaned_text"], rec["sentences"])):
                pool.append(item)
        rng.shuffle(pool)
        for item in pool:
            if item["source_page"] in used_pages:
                continue
            selected.append({"id": item["id"], "source_page": item["source_page"],
                             "stratum": stratum})
            used_pages.add(item["source_page"])
            if sum(x["stratum"] == stratum for x in selected) == target:
                break
        if sum(x["stratum"] == stratum for x in selected) != target:
            raise ValueError(f"insufficient_{stratum}")
    manifest = {"seed": SEED, "source_sha256": hashlib.sha256(a.unified.read_bytes()).hexdigest(),
                "audit_sha256": hashlib.sha256(a.audit.read_bytes()).hexdigest(),
                "n": len(selected), "positive_proxy": 50, "hard_negative_proxy": 20,
                "warning": "strata are sampling proxies, not gold labels; no model calls", "records": selected}
    (a.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    with (a.out / "blind-review.jsonl").open("x", encoding="utf-8", newline="\n") as f:
        for item in selected:
            rec = records[item["id"]]
            clauses = candidate_fact_clauses(rec["cleaned_text"], rec["sentences"])
            review = {"id": item["id"], "source_page": item["source_page"],
                      "cleaned_sha256": hashlib.sha256(rec["cleaned_text"].encode()).hexdigest(),
                      "cleaned_text": rec["cleaned_text"],
                      "clauses": [{**c, "review_role": None, "review_note": None} for c in clauses],
                      "eligible_for_teacher_input": None, "eligibility_reason": None,
                      "reviewer": None, "reviewed_at": None}
            f.write(json.dumps(review, ensure_ascii=False) + "\n")
    print(json.dumps({"records": len(selected), "candidate_proxy": 50, "hard_negative_proxy": 20,
                      "executed": False}))


if __name__ == "__main__":
    main()

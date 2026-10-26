"""Freeze a source-grounded, event-disjoint S1 diagnostic smoke cohort."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from durable_calls import read_rows

SOURCES = ("20261018-P1-r6", "20261018-P1b-r2", "20261018-P2-L4word", "merged-20261017-full")
TARGET = {"20261018-P2-L4word": 7, "merged-20261017-full": 5}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("batch", "parsed-root", "dev-slice", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error("output already exists")
    parsed = {batch: {r["id"]: r for r in read_rows(a.parsed_root / "pkulaw" / batch / "records.jsonl")}
              for batch in SOURCES}
    dev = list(read_rows(a.dev_slice))
    dev_ids = {r["id"] for r in dev}
    dev_hashes = {r["text_orig_sha256"] for r in dev}
    counts, eligible = Counter(), []
    for row in read_rows(a.batch):
        counts["input"] += 1
        if row.get("channel") != "pkulaw" or row.get("split") != "test":
            continue
        counts["pkulaw_test"] += 1
        batch = row.get("source_batch")
        src = parsed.get(batch, {}).get(row.get("source_id"))
        if not src or row.get("source_id") in dev_ids or row.get("text_orig_sha256") in dev_hashes:
            continue
        counts["source_not_dev"] += 1
        q = src.get("quality") or {}
        comp = q.get("completeness") or {}
        if not (row.get("grade") == "A" and row.get("party_available")
                and row.get("form") == "叙述式-独立成篇" and row.get("source_type") == "处罚决定书"
                and str(q.get("tier", "")).startswith("L1") and q.get("in_scope")
                and comp.get("has_amount") and comp.get("has_outcome")
                and not q.get("parse_warnings") and not q.get("facts_contains_conclusion")):
            continue
        counts["quality_fields"] += 1
        facts, decision = src.get("text_facts") or "", src.get("text_decision") or ""
        subject = src.get("subject_mention") or ""
        if re.search(r"行政处罚决定书|下载日期|主题分类|法宝引证码", facts):
            counts["source_cross_document_bleed"] += 1
            continue
        behavior_date, decision_date = src.get("behavior_date") or "", src.get("decision_date") or ""
        if (len(behavior_date) >= 7 and len(decision_date) >= 7
                and behavior_date[:7] > decision_date[:7]):
            counts["inconsistent_source_dates"] += 1
            continue
        if not (len(facts) >= 60 and len(decision) >= 20 and subject
                and subject in facts and subject in decision
                and re.search(r"(?:拘留|罚款).{0,25}(?:元|日)", decision)):
            continue
        counts["text_grounded"] += 1
        eligible.append((row, src))
    selected, events = [], set()
    for batch, target in TARGET.items():
        pool = sorted((pair for pair in eligible if pair[0]["source_batch"] == batch),
                      key=lambda pair: hashlib.sha256(pair[0]["id"].encode()).hexdigest())
        for row, src in pool:
            if row["event_id"] in events:
                continue
            selected.append((row, src))
            events.add(row["event_id"])
            if sum(r["source_batch"] == batch for r, _ in selected) == target:
                break
        if sum(r["source_batch"] == batch for r, _ in selected) != target:
            raise ValueError(f"insufficient distinct events in {batch}")
    a.out.mkdir(parents=True)
    ids = [r["id"] for r, _ in selected]
    (a.out / "ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n", "utf-8")
    manifest = {"version": "quality-s1-screen-2", "source_batch_sha256": hashlib.sha256(a.batch.read_bytes()).hexdigest(),
                "dev_slice_sha256": hashlib.sha256(a.dev_slice.read_bytes()).hexdigest(),
                "screen": "test split; pkulaw; grade A; L1/in-scope; party; narrative decision; quantified, subject-grounded facts+decision; no parse warnings/conclusion, contradictory source dates or cross-document metadata in facts; dev slice excluded",
                "funnel": dict(counts), "eligible_records": len(eligible),
                "eligible_events": len({r["event_id"] for r, _ in eligible}),
                "selected": [{"id": r["id"], "source_id": r["source_id"], "source_batch": r["source_batch"],
                              "event_id": r["event_id"], "text_orig_sha256": r["text_orig_sha256"],
                              "parsed_outcome": src.get("outcome")}
                             for r, src in selected],
                "warning": "parsed fields are source-grounded proxies, not independently adjudicated gold labels",
                "executed": False}
    (a.out / "quality-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"eligible_records": len(eligible), "eligible_events": manifest["eligible_events"],
                      "selected": len(ids), "batches": dict(Counter(r["source_batch"] for r, _ in selected)),
                      "executed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

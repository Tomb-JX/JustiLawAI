"""Freeze every source-qualified narrative S1 candidate from the clean latest input."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from durable_calls import read_rows


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--parsed-root", type=Path, required=True)
    p.add_argument("--reuse-run", type=Path, required=True)
    p.add_argument("--reuse-unified", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error("output already exists")
    reuse = {x["id"]: x for x in read_rows(a.reuse_run / "outputs.jsonl")}
    old = {x["id"]: x for x in read_rows(a.reuse_unified) if x["id"] in reuse}
    if len(reuse) != 57 or len(old) != 57:
        raise ValueError("reuse cohort incomplete")
    old_by_source = {(rid, old[rid]["text_orig_sha256"]): rid for rid in reuse}
    parsed_cache = {}
    counts = Counter()
    selected = []
    for rec in read_rows(a.batch):
        counts["input"] += 1
        if rec.get("grade") != "A" or rec.get("channel") not in {"web", "pkulaw"}:
            continue
        counts["grade_A"] += 1
        if (rec.get("form") != "叙述式-独立成篇" or rec.get("source_type") != "处罚决定书"
                or not rec.get("party_available") or not (rec.get("prefilter") or {}).get("release")):
            continue
        counts["narrative_party"] += 1
        key = (rec["channel"], rec["source_batch"])
        if key not in parsed_cache:
            path = a.parsed_root / key[0] / key[1] / "records.jsonl"
            parsed_cache[key] = {x["id"]: x for x in read_rows(path)}
        src = parsed_cache[key].get(rec["source_id"])
        if not src:
            counts["missing_source"] += 1
            continue
        q = src.get("quality") or {}
        comp = q.get("completeness") or {}
        if (not str(q.get("tier", "")).startswith("L1") or not q.get("in_scope")
                or not comp.get("has_amount") or not comp.get("has_outcome")
                or q.get("parse_warnings") or q.get("facts_contains_conclusion")):
            continue
        counts["source_quality"] += 1
        facts, decision = src.get("text_facts") or "", src.get("text_decision") or ""
        subject = src.get("subject_mention") or ""
        if (len(facts) < 60 or len(decision) < 20 or not subject or subject not in facts
                or subject not in decision or not re.search(r"(?:拘留|罚款).{0,25}(?:元|日)", decision)):
            continue
        counts["text_grounded"] += 1
        if re.search(r"行政处罚决定书|下载日期|主题分类|法宝引证码", facts):
            counts["cross_document_bleed"] += 1
            continue
        behavior, decided = src.get("behavior_date") or "", src.get("decision_date") or ""
        if len(behavior) >= 7 and len(decided) >= 7 and behavior[:7] > decided[:7]:
            counts["contradictory_source_dates"] += 1
            continue
        match = old_by_source.get((rec["source_id"], rec["text_orig_sha256"]))
        if match and (rec["cleaned_text"] != old[match]["cleaned_text"]
                      or rec["sentences"] != old[match]["sentences"]):
            match = None
            counts["same_source_changed_s0_view"] += 1
        selected.append({"id": rec["id"], "source_id": rec["source_id"], "source_batch": rec["source_batch"],
                         "event_id": rec["event_id"], "split": rec["split"],
                         "text_orig_sha256": rec["text_orig_sha256"], "reuse_output_id": match})
    if len({x["id"] for x in selected}) != len(selected):
        raise ValueError("duplicate selected IDs")
    a.out.mkdir(parents=True)
    ids = [x["id"] for x in selected]
    missing = [x["id"] for x in selected if not x["reuse_output_id"]]
    (a.out / "ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (a.out / "missing-ids.json").write_text(json.dumps(missing, ensure_ascii=False, indent=2) + "\n", "utf-8")
    manifest = {"version": "l5-quality-pool-1", "source_sha256": sha(a.batch),
                "reuse_outputs_sha256": sha(a.reuse_run / "outputs.jsonl"),
                "reuse_unified_sha256": sha(a.reuse_unified), "criteria": "all splits; grade A; released independent narrative decision; party; parsed L1/in_scope complete quantified facts+decision; no parse warning/conclusion/date contradiction/cross-document bleed",
                "funnel": dict(counts), "selected": len(selected), "reused": len(ids) - len(missing),
                "requires_s1": len(missing), "by_split": dict(Counter(x["split"] for x in selected)),
                "by_batch": dict(Counter(x["source_batch"] for x in selected)),
                "events": len({x["event_id"] for x in selected}), "records": selected,
                "warning": "source-screened candidate, not gold; reused old IDs require exact source/hash and cleaned sentence view"}
    (a.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in ("selected", "reused", "requires_s1", "events", "by_split", "by_batch", "funnel")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Offline S3 and downstream-view audit for frozen baseline and clause pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from durable_calls import read_rows
from fact_spans import fact_view
from locate import OffsetIndex
from run_elements import build_inputs
from s3 import run_checks, zone_spans


def evaluate(rec, output):
    spans = zone_spans(output, rec["sentences"], None)
    findings = run_checks({"record": rec, "output": output, "sentences": rec["sentences"], "spans": spans})
    return {"status": "error" if any(f.severity == "error" for f in findings)
            else "warn" if findings else "pass",
            "errors": [f.as_dict() for f in findings if f.severity == "error"]}


def audit(unified: Path, edits: Path, parsed: Path, baseline: Path, pilot: Path) -> dict:
    recs = {r["id"]: r for r in read_rows(unified)}
    edit_rows = {r["id"]: r for r in read_rows(edits)}
    sources = {r["id"]: r for r in read_rows(parsed)}
    old = {r["id"]: r["output"] for r in read_rows(baseline / "outputs.jsonl") if r.get("ok")}
    new = {r["id"]: r["output"] for r in read_rows(pilot / "outputs.jsonl") if r.get("ok")}
    base_status = {rid: evaluate(recs[rid], output)["status"] for rid, output in old.items()}
    paired = []
    for rid, output in new.items():
        rec = dict(recs[rid]); rec["_text_full"] = sources[rid]["text_full"]
        if hashlib.sha256(rec["_text_full"].encode()).hexdigest() != rec["text_orig_sha256"]:
            raise ValueError(f"source mismatch: {rid}")
        index = OffsetIndex(edit_rows[rid])
        old_input = build_inputs(rec, old[rid], index)
        new_input = build_inputs(rec, output, index)
        view = fact_view(rec, output)
        paired.append({"id": rid, "baseline_s3": base_status[rid], "pilot_s3": evaluate(rec, output),
                       "baseline_facts_text": old_input["facts_text"] if old_input else None,
                       "pilot_facts_text": new_input["facts_text"] if new_input else None,
                       "pilot_view_hash": new_input["view_hash"] if new_input else None,
                       "fact_view": view})
    return {"baseline_count": len(old), "baseline_status_counts": {x: list(base_status.values()).count(x)
                                                              for x in ("error", "warn", "pass")},
            "pilot_count": len(new), "paired": paired, "release_approved": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("unified", "edits", "parsed", "baseline", "pilot", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    result = audit(a.unified, a.edits, a.parsed, a.baseline, a.pilot)
    with a.out.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "paired"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

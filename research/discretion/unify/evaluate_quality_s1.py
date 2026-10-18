"""Compare a frozen high-quality S1 trial with source proxies and S3 checks."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from durable_calls import read_rows
from s3 import run_checks, zone_spans, zone_text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--trial", type=Path, required=True)
    ap.add_argument("--parsed-root", type=Path, required=True)
    ap.add_argument("--run", type=Path, action="append", help="S1 run directory; repeat to combine disjoint trials")
    a = ap.parse_args()
    manifest = json.loads((a.trial / "quality-manifest.json").read_text("utf-8"))
    selected = {x["id"]: x for x in manifest["selected"]}
    records = {x["id"]: x for x in read_rows(a.batch) if x["id"] in selected}
    run_dirs = a.run or [a.trial / "seg-run"]
    outputs = {}
    for run_dir in run_dirs:
        for output in read_rows(run_dir / "outputs.jsonl"):
            if output["id"] not in selected:
                continue
            if output["id"] in outputs:
                raise ValueError(f"duplicate output ID: {output['id']}")
            outputs[output["id"]] = output
    sources = {}
    for item in selected.values():
        batch = item["source_batch"]
        if batch not in sources:
            sources[batch] = {x["id"]: x for x in read_rows(a.parsed_root / "pkulaw" / batch / "records.jsonl")}
    rows = []
    for id_, item in selected.items():
        rec, raw = records[id_], outputs[id_]
        src = sources[item["source_batch"]][item["source_id"]]
        if not raw.get("ok"):
            rows.append({"id": id_, "ok": False, "validation_errors": raw.get("validation_errors")})
            continue
        out = raw["output"]
        spans = zone_spans(out, rec["sentences"], None)
        findings = [f.as_dict() for f in run_checks({"record": rec, "output": out,
                                                    "sentences": rec["sentences"], "spans": spans})]
        status = "error" if any(f["severity"] == "error" for f in findings) else "warn" if findings else "pass"
        rows.append({"id": id_, "source_id": item["source_id"], "source_batch": item["source_batch"],
                     "ok": True, "s3_status": status, "findings": findings,
                     "subject_source": src.get("subject_mention"), "subject_s1": out.get("subject"),
                     "outcome_source": src.get("outcome"), "outcome_s1": out.get("outcome"),
                     "facts_source": src.get("text_facts"), "facts_s1": zone_text(spans, rec["cleaned_text"], "facts"),
                     "decision_source": src.get("text_decision"),
                     "decision_s1": zone_text(spans, rec["cleaned_text"], "decision"),
                     "fact_clause_ids": out.get("fact_clause_ids"), "fact_clause_roles": out.get("fact_clause_roles"),
                     "dates_source": {k: src.get(k) for k in ("behavior_date", "decision_date")},
                     "dates_s1": out.get("dates")})
    report = {"selected": len(selected), "returned": len(outputs),
              "status": dict(Counter(x.get("s3_status", "failed") for x in rows)), "rows": rows,
              "warning": "Source parsed fields are proxies, not independent gold labels; null edit index preserves clean-text checks only."}
    dest = a.trial / "quality-eval.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"selected": report["selected"], "returned": report["returned"],
                      "status": report["status"], "report": str(dest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

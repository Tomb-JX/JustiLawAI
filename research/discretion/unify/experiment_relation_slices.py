"""Small-support valid slice diagnostics for fixed relation-suite operating points."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from experiment_participant_list import candidate_lists
from experiment_silver_supervised_pipeline import measure
from minimal_amount_closure import load_records

ROUTES = (("amounts.personal_stake", "local_relation", None),
          ("amounts.onsite_stake_total", "local_relation", None),
          ("persons.participant_count", "surface", "plus_silver_missing"))


def run(teacher: Path, originals: Path, silver: Path,
        suite_report: Path, suite_predictions: Path) -> dict:
    report = json.loads(suite_report.read_text("utf-8"))
    records = load_records(teacher, originals, silver, {"valid"})
    by_id = {rid: (inp, packet, ref) for rid, inp, packet, ref in records}
    predictions = [r for r in rows(suite_predictions)]
    out = {"scope": "valid_small_support_slice_diagnostic", "test_labels_read": False,
           "valid_records": len(records), "slices": {},
           "input_sha256": {"suite_report": hashlib.sha256(suite_report.read_bytes()).hexdigest(),
                            "suite_predictions": hashlib.sha256(suite_predictions.read_bytes()).hexdigest()}}
    strata = {}
    for rid, (inp, packet, ref) in by_id.items():
        amounts = [q for q in packet["quantities"] if q["type"] == "amount"
                   and q["parse_status"] == "resolved"]
        lists = candidate_lists(packet, inp["target"], inp.get("aliases") or ())
        prior = any(s["kind"] == "prior_penalty" for s in packet["scenes"])
        strata[rid] = {"multi_amount": len(amounts) >= 2,
                       "list_candidate": bool(lists), "prior_scene": prior}
    for field, config, policy in ROUTES:
        route = report["amounts"][field][config] if policy is None else report["count"][policy][config]
        selected = [r for r in predictions if r["field"] == field and r["config"] == config
                    and r.get("policy") == policy]
        if len(selected) != len(records):
            raise ValueError("route_record_scope_mismatch:" + field)
        out["slices"][field] = {"all": {"events": len({by_id[r["id"]][2]["metadata"].get("event_id")
                                                        or r["id"] for r in selected}),
                                       "metric": measure(selected, route["threshold"])}}
        for name in ("multi_amount", "list_candidate", "prior_scene"):
            subset = [r for r in selected if strata[r["id"]][name]]
            out["slices"][field][name] = {"records": len(subset),
                                            "events": len({by_id[r["id"]][2]["metadata"].get("event_id")
                                                           or r["id"] for r in subset}),
                                            "metric": measure(subset, route["threshold"])}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "suite_report", "suite_predictions", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    result = run(args.teacher, args.originals, args.silver,
                 args.suite_report, args.suite_predictions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({f: {s: {"records": d.get("records", d["metric"].get("records", 0)),
                               "tp": d["metric"].get("tp", 0), "fp": d["metric"].get("fp", 0)}
                          for s, d in ss.items()} for f, ss in result["slices"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

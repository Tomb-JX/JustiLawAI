"""Build a small choice-based blind amount-binding review from existing cases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from audit_supply_replay import rows

PILOT_IDS = (
    "S1-11b12d1888326c732d8a",
    "S1-7cfbd0e8e2478be67565",
    "S1-f9f067debee7744d2346",
    "S1-dfd6231d472211c3381c",
    "S1-72c37d6c48b386a983cc",
    "S1-582686ced1f819c3d6ae",
)


def run(cases_path: Path, output_path: Path) -> dict:
    if output_path.exists():
        raise ValueError("output_already_exists")
    by_id = {case["id"]: case for case in rows(cases_path)}
    if any(rid not in by_id for rid in PILOT_IDS):
        raise ValueError("pilot_case_missing")
    cases = []
    for rid in PILOT_IDS:
        case = by_id[rid]
        amounts = [q for q in case["candidates"] if q["type"] == "amount"]
        for q in amounts:
            if not any(v["start"] <= q["start"] < q["end"] <= v["end"] and
                       v["text"][q["start"]-v["start"]:q["end"]-v["start"]] == q["raw"]
                       for v in case["allowed_views"]):
                raise ValueError("candidate_not_grounded:" + rid)
        cases.append({k: case[k] for k in ("id", "source_sha256", "target", "aliases", "allowed_views")}
                     | {"amounts": amounts})
    template = Path(__file__).with_name("simple_review_ui_template.html").read_text("utf-8")
    html = template.replace("__CASES_JSON__", json.dumps(cases, ensure_ascii=False).replace("<", "\\u003c"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cases_output = output_path.with_name("simple-cases.json")
    if cases_output.exists():
        raise ValueError("cases_output_already_exists")
    cases_output.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", "utf-8")
    output_path.write_text(html, "utf-8")
    return {"case_count": len(cases), "amount_counts": [len(c["amounts"]) for c in cases],
            "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            "pilot_cases_sha256": hashlib.sha256(cases_output.read_bytes()).hexdigest(),
            "html_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.cases, args.out), ensure_ascii=False))


if __name__ == "__main__":
    main()

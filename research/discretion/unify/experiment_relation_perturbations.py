"""Constructed semantic counterexamples for frozen amount, list and age routes.

These are executable invariants, not a random sample or an accuracy estimate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from experiment_age_count_closure import age_prediction
from experiment_participant_list import proposed_count
from minimal_amount_closure import bind_import, predict_record
from supply_packet import build_packet


CASES = [
    {"id": "amount-single", "target": "甲", "facts": "甲持有赌资500元，现场查获赌资1500元。",
     "expect": {"personal": 500, "onsite": 1500}},
    {"id": "amount-two-actors-target-a", "target": "甲",
     "facts": "甲持有赌资500元，乙持有赌资1000元，现场查获赌资1500元。",
     "expect": {"personal": 500, "onsite": 1500}},
    {"id": "amount-two-actors-target-b", "target": "乙",
     "facts": "甲持有赌资500元，乙持有赌资1000元，现场查获赌资1500元。",
     "expect": {"personal": 1000, "onsite": 1500}},
    {"id": "amount-joint-undistributed", "target": "甲", "facts": "甲与乙共同持有赌资500元。",
     "expect": {"personal": None, "onsite": None}},
    {"id": "amount-respectively-target-b", "target": "乙",
     "facts": "甲、乙分别持有赌资500元、1000元，现场查获赌资1500元。",
     "expect": {"personal": 1000, "onsite": 1500}},
    {"id": "amount-prior-penalty", "target": "甲",
     "facts": "甲曾因赌博被罚款500元，本次赌博现场查获赌资1500元。",
     "expect": {"personal": None, "onsite": 1500}},
    {"id": "list-redacted-collision", "target": "杨**",
     "facts": "杨**、陈**、杨**、杨**在院内赌博。", "expect": {"count": 4}},
    {"id": "list-open-ended", "target": "杨**",
     "facts": "杨**、陈**、杨**、杨**等人在院内赌博。", "expect": {"count": None}},
    {"id": "list-nonparticipant-provider", "target": "丁xx",
     "facts": "张x、王x、李x在屋内赌博，丁xx提供场地。", "expect": {"count": None}},
    {"id": "list-two-scenes", "target": "张x",
     "facts": "张x、王x、李x在屋内赌博。张x、赵x在另一日赌博。", "expect": {"count": None}},
    {"id": "age-exact", "target": "甲", "meta": "甲于1990年1月18日出生。",
     "facts": "2023年1月18日甲在屋内赌博。", "expect": {"age": 33}},
    {"id": "age-prior-date", "target": "甲", "meta": "甲于1990年1月18日出生。",
     "facts": "甲曾于2020年1月18日因赌博被处罚。2023年1月18日甲在屋内赌博。",
     "expect": {"age": 33}},
    {"id": "age-year-imprecise", "target": "甲", "meta": "甲于1990年出生。",
     "facts": "2023年1月18日甲在屋内赌博。", "expect": {"age": None}},
    {"id": "age-birthday-boundary", "target": "甲", "meta": "甲于1990年1月18日出生。",
     "facts": "2023年1月17日甲在屋内赌博。", "expect": {"age": 32}},
]


def case_packet(case: dict) -> tuple[dict, dict]:
    meta, facts = case.get("meta", ""), case["facts"]
    text = meta + facts
    views = []
    if meta:
        views.append({"id": "meta", "type": "meta", "start": 0, "end": len(meta), "text": meta})
    views.append({"id": "facts", "type": "facts", "start": len(meta),
                  "end": len(text), "text": facts})
    inp = {"id": case["id"], "target": case["target"], "aliases": [],
           "sentence_view": views, "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
    return inp, build_packet(text, inp, record_id=case["id"])


def projected_int(pred: dict) -> int | None:
    if pred["status"] != "selected":
        return None
    value = pred["value"]
    if isinstance(value, int):
        return value
    if isinstance(value, dict) and value.get("min") == value.get("max"):
        return int(value["min"])
    return None


def run(artifact_path: Path, engine_root: Path) -> dict:
    artifact = json.loads(artifact_path.read_text("utf-8"))
    bind = bind_import(engine_root)
    details = []
    stats = Counter()
    for case in CASES:
        inp, packet = case_packet(case)
        expected = case["expect"]
        if "personal" in expected:
            output = predict_record(case["id"], inp, packet, artifact, bind)["fields"]
            actual = {"personal": projected_int(output["amounts.personal_stake"]),
                      "onsite": projected_int(output["amounts.onsite_stake_total"])}
            route = "frozen_amount"
        elif "count" in expected:
            output = proposed_count(packet, case["target"])
            actual = {"count": output["value"] if output["status"] == "selected" else None}
            route = "provisional_list"
        else:
            output = age_prediction(packet)
            actual = {"age": output["value"] if output["status"] == "selected" else None}
            route = "age_derivation"
        checks = {k: actual[k] == v for k, v in expected.items()}
        stats[route + ":checks"] += len(checks)
        stats[route + ":passed"] += sum(checks.values())
        details.append({"id": case["id"], "route": route, "target": case["target"],
                        "text": case.get("meta", "") + case["facts"], "source_sha256": inp["source_sha256"],
                        "expected": expected, "actual": actual, "checks": checks,
                        "pass": all(checks.values())})
    return {"scope": "constructed_semantic_perturbations", "not_population_accuracy": True,
            "amount_artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "cases": len(details), "stats": dict(stats), "details": details}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact", "engine_root", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    result = run(args.artifact, args.engine_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"cases": result["cases"], "stats": result["stats"],
                      "failed": [x["id"] for x in result["details"] if not x["pass"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

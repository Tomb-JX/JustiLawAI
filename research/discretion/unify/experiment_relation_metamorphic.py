"""Target-name substitution stability on all 203 teacher-visible inputs.

This changes only equal-length target characters, preserving offsets and all
numeric facts. Stability is not evidence of semantic correctness.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from experiment_age_count_closure import predict_record as predict_age_count, source_records
from experiment_participant_list import proposed_count
from minimal_amount_closure import bind_import, predict_record as predict_amount
from supply_packet import build_packet


def renamed_target(value: str) -> str:
    return "".join("靳" if "\u4e00" <= c <= "\u9fff" else c for c in value)


def rename_record(inp: dict, text: str) -> tuple[dict, str] | None:
    target = inp["target"]
    replacement = renamed_target(target)
    if not target or target == replacement or replacement in text or inp.get("aliases"):
        return None
    new_text = text.replace(target, replacement)
    if new_text == text or len(new_text) != len(text):
        return None
    output = copy.deepcopy(inp)
    output["target"] = replacement
    output["source_sha256"] = hashlib.sha256(new_text.encode()).hexdigest()
    for view in output["sentence_view"]:
        view["text"] = new_text[view["start"]:view["end"]]
    return output, new_text


def result_key(pred: dict) -> tuple:
    if pred["status"] != "selected":
        return ("abstain",)
    value = pred["value"]
    return ("selected", json.dumps(value, ensure_ascii=False, sort_keys=True))


def run(teacher: Path, originals: Path, amount_artifact: Path,
        age_count_artifact: Path, engine_root: Path) -> dict:
    amount = json.loads(amount_artifact.read_text("utf-8"))
    age_count = json.loads(age_count_artifact.read_text("utf-8"))
    bind = bind_import(engine_root)
    origins = {r["id"]: r["text_full"] for r in rows(originals)}
    stats = Counter()
    changes = []
    for rid, inp, packet in source_records(teacher, originals):
        stats["records"] += 1
        renamed = rename_record(inp, origins[rid])
        if renamed is None:
            stats["excluded_non_preserving_or_alias"] += 1
            continue
        new_inp, new_text = renamed
        new_packet = build_packet(new_text, new_inp, record_id=rid)
        stats["evaluated"] += 1
        a0 = predict_amount(rid, inp, packet, amount, bind)["fields"]
        a1 = predict_amount(rid, new_inp, new_packet, amount, bind)["fields"]
        b0 = predict_age_count(rid, inp, packet, age_count)["fields"]
        b1 = predict_age_count(rid, new_inp, new_packet, age_count)["fields"]
        l0 = proposed_count(packet, inp["target"], inp.get("aliases") or ())
        l1 = proposed_count(new_packet, new_inp["target"], new_inp.get("aliases") or ())
        pairs = {**{f: (a0[f], a1[f]) for f in a0},
                 **{f: (b0[f], b1[f]) for f in b0}, "list_proposal": (l0, l1)}
        for field, (before, after) in pairs.items():
            old, new = result_key(before), result_key(after)
            stats[field + ":evaluated"] += 1
            stats[field + ":changed"] += old != new
            if old != new:
                changes.append({"id": rid, "field": field, "before": old, "after": new,
                                "target_before": inp["target"], "target_after": new_inp["target"]})
    return {"scope": "unlabeled_equal_length_target_rename", "silver_labels_read": False,
            "stability_not_accuracy": True, "counts": dict(stats), "changes": changes,
            "input_sha256": {k: hashlib.sha256(p.read_bytes()).hexdigest()
                             for k, p in {"teacher": teacher, "originals": originals,
                                          "amount_artifact": amount_artifact,
                                          "age_count_artifact": age_count_artifact}.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "amount_artifact", "age_count_artifact", "engine_root", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    result = run(args.teacher, args.originals, args.amount_artifact,
                 args.age_count_artifact, args.engine_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Merge quality-gated P9 silver labels into the frozen M4 clean base.

Only facts_text is exposed as input. Existing validation cohorts stay frozen.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


# Frozen E2/E3 rules from m4_clean_gate.py (v3-clean), copied here so the
# merger can reproduce its decision without importing a sibling worktree.
RECON_PAT = re.compile(r"被申请人|答复称|复议|请求撤销|申请人(?:称|诉|因|不服|请求)|不服.{0,12}(?:决定|处罚)|撤销.{0,12}决定")
COMBINED_PAT = re.compile(r"合并执行|分别决定|分别裁决|合并处罚|数罪并罚|两个以上行为|数个行为")
GAMBLING_PAT = re.compile(r"赌|麻将|扑克|六合彩|时时彩|百家乐|十三水|十三张|斗地主|炸金花|押注|下注|庄家|抽头|台费|博彩|私彩|彩票|骰子|老虎机|打鱼机|游意")


def mechanism_of(target: dict) -> tuple[str, list[str]]:
    days = float(target["detention_days"])
    fine = float(target["fine"])
    kind = target["type"]
    flags = []
    if days > 15:
        flags.append("combined_enforcement(days>15,第16条)")
    if 6 <= days <= 9:
        flags.append("mitigated_below_range(days6-9,第19条幅度以下)")
    if kind == "拘留并处罚款" and 0 < fine < 500:
        flags.append("mitigated_both_fine(<500,并处减轻)")
    if fine > 3000:
        flags.append("exceeds_cap(fine>3000,第70条上限外)")
    if not flags:
        return "base", flags
    mechanism = "combined" if any(flag.startswith("combined") for flag in flags) else "mitigated"
    if any(flag.startswith("exceeds") for flag in flags):
        mechanism = "review"
    return mechanism, flags


BASE_FILES = ("train.jsonl", "old168.jsonl", "lake706_valid70.jsonl", "p3p7_valid119.jsonl")


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--p9", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)

    base = {name: read(args.base / name) for name in BASE_FILES}
    p9 = read(args.p9 / "eligible_s1_text.jsonl")
    p9_manifest = json.loads((args.p9 / "manifest.json").read_text(encoding="utf-8"))
    if len(p9) != p9_manifest["counts"]["accepted"]:
        raise ValueError("P9 accepted count differs from manifest")
    seen_ids = {row["id"] for rows in base.values() for row in rows}
    seen_events = {row["event_id"] for rows in base.values() for row in rows}
    if len(seen_ids) != sum(map(len, base.values())):
        raise ValueError("Base contains duplicate IDs")
    base_splits = defaultdict(set)
    for name, rows in base.items():
        for row in rows:
            base_splits[row["event_id"]].add(name)

    accepted = {"train": [], "p9_valid": []}
    excluded = []
    audit = []
    incoming_ids = set()
    incoming_split = {}
    for row in p9:
        ident = row["id"]
        event = row["event_id"]
        split = row["split"]
        if split not in ("train", "valid"):
            raise ValueError(f"Unexpected split: {split}")
        if ident in incoming_ids:
            raise ValueError(f"Duplicate P9 ID: {ident}")
        incoming_ids.add(ident)
        if event in incoming_split and incoming_split[event] != split:
            raise ValueError(f"P9 event crosses splits: {event}")
        incoming_split[event] = split
        facts = row["facts_text"]
        target = row["observed_outcome"]
        reasons = []
        if ident in seen_ids:
            reasons.append("base_id_duplicate")
        if event in seen_events:
            reasons.append("base_event_duplicate")
        if RECON_PAT.search(facts):
            reasons.append("E2a_reconsideration_candidate")
        if not GAMBLING_PAT.search(facts):
            reasons.append("E2b_non_gambling_candidate")
        if not facts.strip():
            reasons.append("empty_facts")
        if reasons:
            excluded.append({"id": ident, "event_id": event, "split": split, "reasons": reasons,
                             "base_splits": sorted(base_splits.get(event, []))})
            continue
        mechanism, flags = mechanism_of(target)
        if mechanism == "review":
            excluded.append({"id": ident, "event_id": event, "split": split,
                             "reasons": ["E3_exceeds_cap_review"], "target": target})
            continue
        if COMBINED_PAT.search(facts):
            audit.append({"id": ident, "event_id": event, "flag": "E2c_combined_trace",
                          "mechanism": mechanism})
        if flags:
            audit.append({"id": ident, "event_id": event, "flag": "E3_mechanism",
                          "mechanism": mechanism, "details": flags})
        converted = {
            "id": ident, "event_id": event, "input": {"facts_text": facts},
            "target": {key: target[key] for key in ("type", "detention_days", "fine")},
            "metadata": {"cohort": "p9", "source_batch": row.get("source_batch"),
                         "channel": row.get("channel"), "source_text_sha256": row.get("source_text_sha256"),
                         "mechanism": mechanism},
            "label_tier": "development_silver", "human_review": row.get("human_review", False),
            "release_approved": False,
        }
        accepted["train" if split == "train" else "p9_valid"].append(converted)

    outputs = {**base, "train.jsonl": base["train.jsonl"] + accepted["train"],
               "p9_valid.jsonl": accepted["p9_valid"]}
    event_owner = {}
    for name, rows in outputs.items():
        for row in rows:
            owner = event_owner.setdefault(row["event_id"], name)
            if owner != name:
                raise ValueError(f"Cross-split event: {row['event_id']} in {owner} and {name}")
    args.out.mkdir(parents=True)
    for name, rows in outputs.items():
        write(args.out / name, rows)
    write(args.out / "excluded.jsonl", excluded)
    write(args.out / "audit.jsonl", audit)
    manifest = {
        "status": "model_ready_development_silver", "release_approved": False,
        "stratified_eval_only": True, "test_scored": False,
        "features_whitelist": ["input.facts_text"],
        "target_fields": ["type", "detention_days", "fine"],
        "source": {"base": str(args.base), "base_manifest_sha256": digest(args.base / "manifest.json"),
                   "p9": str(args.p9), "p9_manifest_sha256": digest(args.p9 / "manifest.json"),
                   "p9_eligible_sha256": digest(args.p9 / "eligible_s1_text.jsonl")},
        "p9_received": len(p9), "p9_added": {key: len(rows) for key, rows in accepted.items()},
        "p9_excluded": dict(Counter(reason for row in excluded for reason in row["reasons"])),
        "records": {name: len(rows) for name, rows in outputs.items()},
        "events": {name: len({row["event_id"] for row in rows}) for name, rows in outputs.items()},
        "outputs": {name: digest(args.out / name) for name in (*outputs, "excluded.jsonl", "audit.jsonl")},
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("p9_received", "p9_added", "p9_excluded", "records", "events")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

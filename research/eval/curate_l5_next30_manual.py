"""Ground a small subset of manual L5 fields; leave every other field unreviewed."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


# Only fields with direct support in the frozen allowed view are drafted.
DECISIONS = {
    "S1-f90b1d2274c794c46da5": {
        "conduct.behavior_type": ("明确", "参与赌博", ["S8.1.1"]),
        "conduct.role": ("明确", "参赌者", ["S8.1.1"]),
    },
    "S1-eca1cc49bea9e945b58d": {
        "conduct.behavior_type": ("明确", "参与赌博", ["S15.1.1", "S16.1.1", "S17.1.1"]),
        "conduct.role": ("推断", "参赌者", ["S15.1.1", "S16.1.1", "S17.1.1"]),
        "conduct.method": ("明确", "其他", ["S16.1.1", "S17.1.1"]),
        "venue.venue_type": ("明确", "经营场所", ["S16.1.1"]),
    },
    "S1-ff12dd79854bd5ac4c28": {
        "conduct.behavior_type": ("明确", "参与赌博", ["S17.1.1", "S18.1.1", "S19.1.1"]),
        "conduct.role": ("推断", "参赌者", ["S17.1.1", "S18.1.1", "S19.1.1"]),
        "amounts.per_bet": ("明确", {"min": 20, "max": None}, ["S18.1.1", "S19.1.1"]),
        "amounts.onsite_stake_total": ("明确", {"min": 43070, "max": 43070}, ["S20.1.1"]),
    },
    "S1-87c47cd1bee2506ba1d2": {
        "conduct.behavior_type": ("明确", "参与赌博", ["S18.1.1", "S19.1.1", "S20.1.1"]),
        "conduct.role": ("推断", "参赌者", ["S18.1.1", "S19.1.1", "S20.1.1"]),
        "conduct.method": ("明确", "麻将", ["S18.1.1"]),
        "amounts.personal_stake": ("明确", {"min": 500, "max": 500}, ["S19.1.1", "S20.1.1"]),
    },
}

QUARANTINE = {
    "S1-c1bb49770488be497ca4": "masked_alias_and_multiple_money_roles_need_binding_review",
    "S1-dd64aa84a74542989cee": "multiple_behavior_and_gain_roles_need_semantic_review",
    "S1-73cae45a6efe8e329576": "several_yao_masked_mentions_target_ambiguous",
    "S1-c57363151a74e07a9474": "repeated_hu_masked_lookout_mentions_target_ambiguous",
    "S1-c87cd90c55c385ec755f": "several_wang_masked_mentions_target_ambiguous",
    "S1-f6c15f2bc28d8e40c27d": "repeated_chen_masked_mentions_target_ambiguous",
}

FIELD_QUARANTINE = {
    "S1-eca1cc49bea9e945b58d": {"amounts.per_bet": "100元起 hard gate not supported; no release"},
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--unify", type=Path, required=True)
    p.add_argument("--manual", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    os.environ.setdefault("JUSTILAW_ENGINE_API", str(a.repo / "justilaw-api"))
    sys.path.insert(0, str(a.repo / "justilaw-api"))
    sys.path.insert(0, str(a.unify))
    from app.discretion.element_labels import FIELD_INFO  # type: ignore
    from element_contract import compile_references, contract_snapshot, digest, engine_contract  # type: ignore

    source = a.manual / "records.jsonl"
    manifest = json.loads((a.manual / "manifest.json").read_text("utf-8"))
    records = [json.loads(line) for line in source.read_text("utf-8").splitlines() if line]
    if len(records) != 10 or {r["id"] for r in records} != set(DECISIONS) | set(QUARANTINE):
        raise ValueError("manual input cohort changed")
    if sha(source) != manifest["records_sha256"]:
        raise ValueError("manual input hash changed")
    engine = engine_contract()
    if digest(contract_snapshot(engine)) != manifest["contract_hash"]:
        raise ValueError("L5 contract changed")
    drafts = []
    for row in records:
        rid = row["id"]
        if rid in QUARANTINE:
            continue
        payload = {}
        for path in FIELD_INFO:
            group, field = path.split(".")
            payload.setdefault(group, {})[field] = {"status": "未提及", "value": None, "evidence": []}
        for path, (status, value, sentence_ids) in DECISIONS[rid].items():
            group, field = path.split(".")
            payload[group][field] = {"status": status, "value": value,
                                     "evidence": [{"sentence_ids": sentence_ids}]}
        try:
            compiled = compile_references(payload, row["input"], row["text_full"], engine)
        except ValueError as exc:
            raise ValueError(f"{rid}: {exc}") from exc
        reviewed = {path: compiled[path.split(".")[0]][path.split(".")[1]] for path in DECISIONS[rid]}
        drafts.append({"id": rid, "event_id": row["event_id"], "view_hash": row["input"]["view_hash"],
                       "source_sha256": row["input"]["source_sha256"], "reviewed_fields": reviewed,
                       "field_quarantine": FIELD_QUARANTINE.get(rid, {}),
                       "scope": "partial_fields_only_other_fields_unreviewed",
                       "label_provenance": "assistant-offline-field-draft", "human_review": False,
                       "release_approved": False})
    a.out.mkdir(parents=True)
    draft_path = a.out / "field_drafts.jsonl"
    draft_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in drafts), "utf-8")
    quarantine_path = a.out / "quarantine.jsonl"
    quarantine_path.write_text("".join(json.dumps({"id": k, "reason": v}, ensure_ascii=False) + "\n"
                                       for k, v in QUARANTINE.items()), "utf-8")
    summary = {"manual_inputs": 10, "partial_draft_records": len(drafts),
               "reviewed_nonempty_fields": sum(len(r["reviewed_fields"]) for r in drafts),
               "quarantined_records": len(QUARANTINE), "full_labels": 0, "training_approved": False,
               "source_sha256": sha(source), "field_drafts_sha256": sha(draft_path),
               "quarantine_sha256": sha(quarantine_path), "contract_hash": manifest["contract_hash"]}
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: summary[k] for k in ("partial_draft_records", "reviewed_nonempty_fields",
                                              "quarantined_records", "full_labels")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Claude (subagent) as the blind C voter for pair-relation labels.

`dump` writes one self-contained task file per record: the same system
instructions and input JSON the API voters receive, plus the person/amount ids
the answer must cover. Subagents read only these files and write raw JSON
answers. `ingest` validates every answer with the API voters' strict validator
and wraps valid ones as `{id}-claude.json` label files; invalid ones are listed
for a retry. Labels stay model drafts, never human gold.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_supply_replay import rows
from experiment_relation_edges import amounts_of
from run_pair_relation_labels import PROMPT_VERSION, SYSTEM, persons_of, prompt_for, validate
from supply_packet import build_packet


def records(batch: Path, ids: set[str] | None = None):
    for r in rows(batch / "inputs.jsonl"):
        if ids is not None and r["id"] not in ids:
            continue
        packet = build_packet(r["text_full"], r, record_id=r["id"])
        if amounts_of(packet):
            yield r, packet, persons_of(packet, r)


def dump(batches: list[Path], tasks: Path, shards: int, only: set[str] | None, prefix: str) -> None:
    tasks.mkdir(parents=True, exist_ok=True)
    ids = []
    for r, packet, persons in (x for b in batches for x in records(b, only)):
        (tasks / f"{r['id']}.task.json").write_text(json.dumps({
            "record_id": r["id"], "instructions": SYSTEM, "input": json.loads(prompt_for(r, packet, persons)),
            "must_cover": {"person_ids": [p["person_id"] for p in persons],
                           "amount_ids": [q["candidate_id"] for q in amounts_of(packet)]}},
            ensure_ascii=False, indent=1), "utf-8")
        ids.append(r["id"])
    for k in range(shards):
        (tasks / f"{prefix}shard-{k}.txt").write_text("\n".join(ids[k::shards]), "utf-8")
    print(json.dumps({"tasks": len(ids), "shards": shards}))


def ingest(batches: list[Path], answers: Path, labels: Path, model: str, only: set[str] | None) -> None:
    ok, bad = 0, []
    for r, packet, persons in (x for b in batches for x in records(b, only)):
        src = answers / f"{r['id']}.json"
        if not src.exists():
            bad.append((r["id"], "missing"))
            continue
        try:
            payload = json.loads(src.read_text("utf-8"))
            validate(payload, packet, persons)
        except Exception as exc:  # noqa: BLE001 - every failure is reported for a retry
            bad.append((r["id"], f"{type(exc).__name__}: {str(exc)[:80]}"))
            continue
        (labels / f"{r['id']}-claude.json").write_text(json.dumps({
            "id": r["id"], "batch": r.get("source_run", ""), "source_sha256": r["source_sha256"], "provider": "claude",
            "model": model, "prompt_version": PROMPT_VERSION, "persons": persons,
            "label_provenance": "model_draft", "human_review": False, "annotation": payload},
            ensure_ascii=False), "utf-8")
        ok += 1
    (answers / "INGEST.json").write_text(json.dumps({"ok": ok, "bad": bad}, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"ok": ok, "bad": len(bad), "examples": bad[:5]}, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("dump", "ingest"))
    ap.add_argument("--batch", type=Path, action="append", required=True)
    ap.add_argument("--ids", type=Path, help="restrict to these record ids")
    ap.add_argument("--prefix", default="", help="shard file name prefix")
    ap.add_argument("--tasks", type=Path)
    ap.add_argument("--shards", type=int, default=7)
    ap.add_argument("--answers", type=Path)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--model", default="claude-subagent")
    args = ap.parse_args()
    only = set(args.ids.read_text("utf-8").split()) if args.ids else None
    if args.stage == "dump":
        dump(args.batch, args.tasks, args.shards, only, args.prefix)
    else:
        ingest(args.batch, args.answers, args.labels, args.model, only)


if __name__ == "__main__":
    main()

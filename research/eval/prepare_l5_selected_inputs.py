"""Build pinned L5 allowed views for a frozen train-only selection, without API calls."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys


TITLE = re.compile(r"行政处罚决定书|不予处罚决定书")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    for name in ("repo", "data", "unify", "selection", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    os.environ.setdefault("JUSTILAW_ENGINE_API", str(a.repo / "justilaw-api"))
    sys.path.insert(0, str(a.unify))
    from run_elements import build_inputs  # type: ignore
    from locate import OffsetIndex  # type: ignore
    from cleanse import replay_edits, sentence_table  # type: ignore
    from s3 import run_checks, zone_spans  # type: ignore
    from element_contract import contract_snapshot, digest, engine_contract, WIRE_VERSION  # type: ignore

    chosen = rows(a.selection)
    chosen_by_id = {r["id"]: r for r in chosen}
    if len(chosen) != 30 or len(chosen_by_id) != 30 or len({r["event_id"] for r in chosen}) != 30:
        raise ValueError("selection is not 30 distinct records and train events")
    eligible_path = a.repo / "research/data/lake-text-706b-audit-v3-20261026/eligible_s1_text.jsonl"
    queue_path = a.repo / "research/data/lake-text-s1-batch-20261021/records.jsonl"
    source_dir = eligible_path.parent / "source_snapshots"
    eligible = {r["id"]: r for r in rows(eligible_path)}
    queue = {r["id"]: r for r in rows(queue_path)}
    outputs = {}
    snapshots = sorted(source_dir.glob("*.jsonl"))
    for path in snapshots:
        for row in rows(path):
            if row.get("ok") and row["id"] in chosen_by_id:
                old = outputs.get(row["id"])
                if old is not None and old != row["output"]:
                    raise ValueError(f"conflicting S1 output: {row['id']}")
                outputs[row["id"]] = row["output"]
    if set(outputs) != set(chosen_by_id):
        raise ValueError("missing S1 output for selected record")
    source_hashes = {str(path): sha(path) for path in (a.selection, eligible_path, queue_path, *snapshots)}
    projected = []
    for batch in sorted({r["source_batch"] for r in chosen}):
        base = a.data / "unified_raw_refresh/20261018-party/pkulaw" / batch
        original_path = a.data / "parsed/pkulaw" / batch / "records.jsonl"
        paths = (base / "records.jsonl", base / "edits.rle.jsonl", original_path)
        source_hashes.update({str(path): sha(path) for path in paths})
        unified = {r["id"]: r for r in rows(paths[0])}
        edits = {r["id"]: r for r in rows(paths[1])}
        originals = {r["id"]: r for r in rows(paths[2])}
        for item in chosen:
            if item["source_batch"] != batch:
                continue
            rid = item["id"]
            erow = eligible[rid]
            qrow = queue[rid]
            if (erow["split"] != "train" or erow["channel"] != "pkulaw"
                    or erow["event_id"] != item["event_id"]
                    or erow["source_batch"] != batch
                    or erow["source_text_sha256"] != item["source_text_sha256"]):
                raise ValueError(f"selection source mismatch: {rid}")
            sid = qrow["source_id"]
            rec = dict(unified[sid])
            rec["_text_full"] = originals[sid]["text_full"]
            if rec["text_orig_sha256"] != qrow["text_orig_sha256"]:
                raise ValueError(f"source hash mismatch: {rid}")
            if (replay_edits(rec["_text_full"], edits[sid]) != rec["cleaned_text"]
                    or sentence_table(rec["cleaned_text"]) != rec["sentences"]):
                raise ValueError(f"source replay mismatch: {rid}")
            index = OffsetIndex(edits[sid])
            checks = run_checks({"record": rec, "output": outputs[rid], "sentences": rec["sentences"],
                                 "spans": zone_spans(outputs[rid], rec["sentences"], index)})
            if any(c.severity == "error" for c in checks):
                raise ValueError(f"S3 hard error: {rid}")
            view = build_inputs(rec, outputs[rid], index)
            if view is None or TITLE.search(view["meta_text"]):
                raise ValueError(f"L5 view rejected or title leaked: {rid}")
            if any(s["text"] != rec["_text_full"][s["start"]:s["end"]] for s in view["sentence_view"]):
                raise ValueError(f"L5 original coordinate mismatch: {rid}")
            projected.append({"id": rid, "source_id": sid, "source_batch": batch,
                              "event_id": item["event_id"], "target": erow["target"],
                              "text_full": rec["_text_full"], "text_orig_sha256": rec["text_orig_sha256"],
                              "input": view, "outcome_type": erow["observed_outcome"]["type"]})
    if len(projected) != 30 or {r["id"] for r in projected} != set(chosen_by_id):
        raise ValueError("not all selected records projected")
    a.out.mkdir(parents=True)
    output_path = a.out / "records.jsonl"
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for row in projected:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Keep all four outcome classes in both channels: five model inputs per class.
    model, manual = [], []
    for outcome in ("不予处罚", "罚款", "拘留", "拘留并处罚款"):
        part = sorted((r for r in projected if r["outcome_type"] == outcome), key=lambda r: r["id"])
        if len(part) not in (7, 8):
            raise ValueError(f"outcome quota changed: {outcome}")
        model.extend(part[:5])
        manual.extend(part[5:])
    if len(model) != 20 or len(manual) != 10:
        raise ValueError("model/manual allocation changed")
    manifest = {"status": "candidate_not_trainable", "release_approved": False, "model_calls": 0,
                "selected_count": 30, "projected_count": len(projected),
                "unique_events": len({r["event_id"] for r in projected}),
                "by_batch": dict(Counter(r["source_batch"] for r in projected)),
                "by_outcome": dict(Counter(r["outcome_type"] for r in projected)),
                "wire_version": WIRE_VERSION,
                "contract_hash": digest(contract_snapshot(engine_contract())),
                "unify_path": str(a.unify),
                "implementation_sha256": {name: sha(a.unify / name) for name in
                                          ("run_elements.py", "s3.py", "field_table.py")},
                "source_hashes": source_hashes, "records_sha256": sha(output_path),
                "next_gate": "L5 hard gate plus independent target-binding quality audit"}
    for channel, part in (("model", model), ("manual", manual)):
        channel_dir = a.out / channel
        channel_dir.mkdir()
        channel_path = channel_dir / "records.jsonl"
        with channel_path.open("w", encoding="utf-8", newline="\n") as f:
            for row in part:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        channel_manifest = {"status": "candidate_not_trainable", "release_approved": False,
                            "model_calls": 0, "channel": channel, "selected_count": len(part),
                            "records_sha256": sha(channel_path), "contract_hash": manifest["contract_hash"],
                            "wire_version": WIRE_VERSION, "parent_selection_sha256": sha(a.selection),
                            "implementation_sha256": manifest["implementation_sha256"]}
        (channel_dir / "manifest.json").write_text(
            json.dumps(channel_manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
        manifest[channel + "_records_sha256"] = channel_manifest["records_sha256"]
        manifest[channel + "_by_outcome"] = dict(Counter(r["outcome_type"] for r in part))
    (a.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in
                      ("selected_count", "projected_count", "unique_events", "contract_hash")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

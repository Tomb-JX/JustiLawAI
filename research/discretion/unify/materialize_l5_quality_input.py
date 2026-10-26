"""Materialize an audited clean S1 input with original text and edit maps."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cleanse import replay_edits, sentence_table
from durable_calls import read_rows


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), "utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("pool", "batch", "unified-root", "parsed-root", "reuse-run", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error("output already exists")
    pool = json.loads((a.pool / "MANIFEST.json").read_text("utf-8"))
    selected = pool["records"]
    by_id = {r["id"]: r for r in read_rows(a.batch)}
    if sha(a.batch) != pool["source_sha256"]:
        raise ValueError("pool source hash changed")
    old = {r["id"]: r for r in read_rows(a.reuse_run / "outputs.jsonl")}
    source_cache, edit_cache = {}, {}
    records, originals, edits, reused = [], [], [], []
    for item in selected:
        rec = by_id[item["id"]]
        key = (rec["channel"], rec["source_batch"])
        if key not in source_cache:
            source_cache[key] = {r["id"]: r for r in read_rows(a.parsed_root / key[0] / key[1] / "records.jsonl")}
            edit_cache[key] = {r["id"]: r for r in read_rows(a.unified_root / key[0] / key[1] / "edits.rle.jsonl")}
        source = source_cache[key][rec["source_id"]]
        edit = edit_cache[key][rec["source_id"]]
        original = source["text_full"]
        if (hashlib.sha256(original.encode("utf-8")).hexdigest() != rec["text_orig_sha256"]
                or replay_edits(original, edit) != rec["cleaned_text"]
                or sentence_table(rec["cleaned_text"]) != rec["sentences"]):
            raise ValueError(f"source replay mismatch: {rec['id']}")
        records.append(rec)
        originals.append({"id": rec["id"], "text_full": original, "source_id": rec["source_id"]})
        edits.append({**edit, "id": rec["id"]})
        if item["reuse_output_id"]:
            prior = old[item["reuse_output_id"]]
            if not prior.get("ok"):
                raise ValueError("reused S1 output not valid")
            reused.append({**prior, "id": rec["id"], "reused_from": item["reuse_output_id"]})
    a.out.mkdir(parents=True)
    write_rows(a.out / "records.jsonl", records)
    write_rows(a.out / "originals.jsonl", originals)
    write_rows(a.out / "edits.rle.jsonl", edits)
    write_rows(a.out / "reused-outputs.jsonl", reused)
    manifest = {"version": "l5-quality-input-1", "pool_sha256": sha(a.pool / "MANIFEST.json"),
                "records": len(records), "reused": len(reused),
                "records_sha256": sha(a.out / "records.jsonl"),
                "originals_sha256": sha(a.out / "originals.jsonl"),
                "edits_sha256": sha(a.out / "edits.rle.jsonl"),
                "reused_outputs_sha256": sha(a.out / "reused-outputs.jsonl"),
                "originals_visibility": "evidence validation only; not teacher prompt"}
    (a.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"records": len(records), "reused": len(reused)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

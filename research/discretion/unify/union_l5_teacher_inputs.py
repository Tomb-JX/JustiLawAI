"""Merge an early L5 handoff with a later screened cohort without duplicate teacher calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from durable_calls import read_rows


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), "utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--first", type=Path, required=True)
    p.add_argument("--later", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error("output already exists")
    first = list(read_rows(a.first / "teacher-inputs.jsonl"))
    later = list(read_rows(a.later / "teacher-inputs.jsonl"))
    seen = {(r["source_sha256"], r["target"]): r for r in first}
    rows, aliases = first.copy(), []
    for row in later:
        key = row["source_sha256"], row["target"]
        original = seen.get(key)
        if original:
            aliases.append({"id": row["id"], "canonical_id": original["id"],
                            "same_view": row["view_hash"] == original["view_hash"]})
        else:
            rows.append(row)
            seen[key] = row
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("ID collision")
    a.out.mkdir(parents=True)
    write(a.out / "teacher-inputs.jsonl", rows)
    write(a.out / "ALIASES.jsonl", aliases)
    manifest = {"version": "l5-teacher-input-union-1", "early": str(a.first.resolve()),
                "later": str(a.later.resolve()), "early_count": len(first), "later_count": len(later),
                "unique_inputs": len(rows), "aliases": len(aliases),
                "view_mismatch_aliases": sum(not r["same_view"] for r in aliases),
                "teacher_inputs_sha256": sha(a.out / "teacher-inputs.jsonl"),
                "aliases_sha256": sha(a.out / "ALIASES.jsonl"), "labels_generated": False}
    (a.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

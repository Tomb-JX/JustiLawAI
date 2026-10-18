"""Export source-grounded facts/meta teacher inputs without decision leakage."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from freeze_slice import leak_reasons
from run_elements import load_work


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), "utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "unified", "parsed", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error("output already exists")
    work, rejected = load_work(a.run, a.unified, a.parsed)
    accepted = []
    for rid, rec, inp in work:
        leaks = sorted({reason for view in inp["sentence_view"] for reason in leak_reasons(view["text"])})
        if leaks:
            rejected.append({"id": rid, "reason": "answer_leakage", "flags": leaks})
            continue
        accepted.append({"id": rid, "target": inp["target"], "aliases": inp["aliases"],
                         "sentence_view": inp["sentence_view"], "facts_text": inp["facts_text"],
                         "meta_text": inp["meta_text"], "view_hash": inp["view_hash"],
                         "fact_view_version": inp["fact_view_version"],
                         "source_sha256": inp["source_sha256"],
                         "label_provenance": "unlabeled-S1-teacher-input"})
    if len({r["id"] for r in accepted}) != len(accepted):
        raise ValueError("duplicate teacher input ID")
    a.out.mkdir(parents=True)
    write_rows(a.out / "teacher-inputs.jsonl", accepted)
    write_rows(a.out / "quarantine.jsonl", rejected)
    manifest = {"version": "l5-teacher-input-1", "source_run": str(a.run.resolve()),
                "source_outputs_sha256": sha(a.run / "outputs.jsonl"),
                "unified_sha256": sha(a.unified), "parsed_sha256": sha(a.parsed),
                "teacher_inputs": len(accepted), "quarantine": len(rejected),
                "quarantine_reasons": dict(Counter(x["reason"] for x in rejected)),
                "teacher_inputs_sha256": sha(a.out / "teacher-inputs.jsonl"),
                "quarantine_sha256": sha(a.out / "quarantine.jsonl"),
                "teacher_visibility": "target, aliases, facts/meta spans only; no decision/reasoning/review/outcome",
                "labels_generated": False}
    (a.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in ("teacher_inputs", "quarantine", "quarantine_reasons")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

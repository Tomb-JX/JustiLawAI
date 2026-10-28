"""Check answer-title leakage on the 127 historically rejected L5 views."""
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
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--unify", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    os.environ.setdefault("JUSTILAW_ENGINE_API", str(a.repo / "justilaw-api"))
    sys.path.insert(0, str(a.unify))
    from run_elements import build_inputs  # type: ignore
    from locate import OffsetIndex  # type: ignore

    rejected_path = a.data / "engine/l5-single-canary-v2-20261026/rejected.jsonl"
    queue_path = a.repo / "research/data/lake-text-s1-batch-20261021/records.jsonl"
    snapshot_dir = a.repo / "research/data/lake-text-706b-audit-v3-20261026/source_snapshots"
    rejected = rows(rejected_path)
    queue = {r["id"]: r for r in rows(queue_path)}
    outputs = {}
    for path in sorted(snapshot_dir.glob("*.jsonl")):
        for row in rows(path):
            if row.get("ok"):
                outputs[row["id"]] = row["output"]
    counters = Counter()
    failures = []
    for batch in sorted({r["source_batch"] for r in rejected}):
        root = a.data / "unified_raw_refresh/20261018-party/pkulaw" / batch
        unified = {r["id"]: r for r in rows(root / "records.jsonl")}
        edits = {r["id"]: r for r in rows(root / "edits.rle.jsonl")}
        original = {r["id"]: r for r in rows(a.data / "parsed/pkulaw" / batch / "records.jsonl")}
        for item in rejected:
            if item["source_batch"] != batch:
                continue
            counters["checked"] += 1
            rid = item["id"]
            sid = queue[rid]["source_id"]
            rec = dict(unified[sid])
            rec["_text_full"] = original[sid]["text_full"]
            view = build_inputs(rec, outputs[rid], OffsetIndex(edits[sid]))
            if view is None:
                failures.append({"id": rid, "reason": "view_rejected"})
                continue
            counters["accepted"] += 1
            if TITLE.search(view["meta_text"]):
                failures.append({"id": rid, "reason": "title_in_meta"})
            if any(s["text"] != rec["_text_full"][s["start"]:s["end"]] for s in view["sentence_view"]):
                failures.append({"id": rid, "reason": "original_span_mismatch"})
    result = {"status": "offline_title_replay", "model_calls": 0,
              "checked": counters["checked"], "accepted": counters["accepted"],
              "failures": failures, "source_sha256": sha(rejected_path),
              "implementation_sha256": {name: sha(a.unify / name) for name in ("field_table.py", "run_elements.py")}}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"checked": result["checked"], "accepted": result["accepted"],
                      "failures": len(failures)}, ensure_ascii=False))
    if counters["checked"] != 127 or counters["accepted"] != 127 or failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

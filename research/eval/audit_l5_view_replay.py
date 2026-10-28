"""Audit a rebuilt L5 mixed batch against its frozen predecessor, without labels."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


TITLE = re.compile(r"行政处罚决定书|不予处罚决定书")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    for name in ("old_model", "old_manual", "new_model", "new_manual", "replay127", "new_manifest"):
        p.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise FileExistsError(a.out)
    paths = {name: getattr(a, name) for name in
             ("old_model", "old_manual", "new_model", "new_manual", "replay127", "new_manifest")}
    old = rows(a.old_model) + rows(a.old_manual)
    new = rows(a.new_model) + rows(a.new_manual)
    prior = json.loads(a.replay127.read_text("utf-8"))
    manifest = json.loads(a.new_manifest.read_text("utf-8"))
    if len(old) != 30 or len(new) != 30 or {r["id"] for r in old} != {r["id"] for r in new}:
        raise ValueError("mixed cohort changed")
    if prior["checked_count"] != 127 or prior["results"] != {"accepted": 127}:
        raise ValueError("127 historical rejects not all resolved")
    new_by_id = {r["id"]: r for r in new}
    audit = Counter()
    old_title_ids = []
    for prior_row in old:
        current = new_by_id[prior_row["id"]]
        old_view, new_view = prior_row["input"], current["input"]
        title_old = bool(TITLE.search(old_view["meta_text"]))
        title_new = bool(TITLE.search(new_view["meta_text"]))
        audit["old_title_meta"] += title_old
        audit["new_title_meta"] += title_new
        if title_old:
            old_title_ids.append(prior_row["id"])
        audit["view_hash_changed"] += old_view["view_hash"] != new_view["view_hash"]
        audit["source_hash_mismatch"] += old_view["source_sha256"] != new_view["source_sha256"]
        audit["facts_text_changed"] += old_view["facts_text"] != new_view["facts_text"]
        text = current["text_full"]
        audit["bad_original_spans"] += sum(
            s["text"] != text[s["start"]:s["end"]] for s in new_view["sentence_view"])
    if audit["new_title_meta"] or audit["source_hash_mismatch"] or audit["facts_text_changed"] or audit["bad_original_spans"]:
        raise ValueError(f"current view audit failed: {dict(audit)}")
    result = {
        "status": "offline_view_replay_pass", "model_calls": 0,
        "mixed_records": 30, "historical_rejects_accepted": 127,
        "old_title_meta": audit["old_title_meta"], "new_title_meta": audit["new_title_meta"],
        "old_title_ids": old_title_ids, "view_hash_changed": audit["view_hash_changed"],
        "source_hash_mismatch": audit["source_hash_mismatch"],
        "facts_text_changed": audit["facts_text_changed"],
        "bad_original_spans": audit["bad_original_spans"],
        "new_contract_hash": manifest["contract_hash"],
        "new_unify_path": manifest["unify_path"],
        "sources": {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()},
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: result[k] for k in
                      ("mixed_records", "historical_rejects_accepted", "old_title_meta", "new_title_meta",
                       "view_hash_changed", "bad_original_spans")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

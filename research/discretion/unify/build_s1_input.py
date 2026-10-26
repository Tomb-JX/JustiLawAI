"""Build a deduplicated, event-grouped S1 input from the refresh catalog.

Inputs are the refreshed unified batches plus the original parsed batches (for
event_key / facts / decision fields). The output is a new records.jsonl with:
- one record per (event, person);
- stable new IDs;
- event-level train/valid/test split;
- no duplicate source page/person across batches.

This does not create labels and does not alter source batches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "s1-input-1"
PRIORITY = {
    "20261018-web-r4-table-repair": 0,
    "20261018-P1-r6": 1,
    "20261018-P1b-r2": 2,
    "20261018-P2-L4word": 3,
    "merged-20261017-full": 4,
    "20261018-P2-r1": 5,
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def source_index(source_root: Path, channel: str, batch: str) -> dict[str, dict]:
    path = source_root / channel / batch / "records.jsonl"
    index: dict[str, dict] = {}
    for row in rows(path):
        # Keep the first occurrence; P2-r1 has repeated IDs and is salvaged below.
        index.setdefault(row.get("id"), row)
    return index


def source_has_content(src: dict) -> bool:
    return bool((src.get("text_facts") or "").strip() or (src.get("text_decision") or "").strip())


def event_id_for(row: dict, src: dict, channel: str) -> tuple[str, str]:
    key = (src.get("event_key") or "").strip()
    if key:
        return key, "event_key"
    doc_key = (src.get("doc_no_hash") or row.get("doc_no_hash") or "").strip()
    if doc_key:
        return "E-" + sha(f"doc|{channel}|{doc_key}")[:20], "doc_no_hash"
    return "E-" + sha(f"text|{row.get('text_orig_sha256') or ''}")[:20], "text_sha"


def split_for(event_id: str) -> str:
    bucket = int(sha(event_id)[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "valid"
    return "test"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-root", type=Path, required=True)
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    catalog = json.loads((args.refresh_root / "CATALOG.json").read_text("utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)

    candidates: list[dict] = []
    no_subject: list[dict] = []
    dropped = Counter()
    for entry in catalog["batches"]:
        if not entry.get("canonical"):
            continue
        channel, batch = entry["channel"], entry["batch"]
        output = entry.get("output") or {}
        fmt_ok = bool(output.get("format_ok"))
        # P2-r1 is salvaged by uniqueness + content; all other canonical batches
        # must already be format_ok.
        if not fmt_ok and batch != "20261018-P2-r1":
            continue
        src_index = source_index(args.source_root, channel, batch)
        seen_ids = set()
        for row in rows(args.refresh_root / channel / batch / "records.jsonl"):
            rid = row.get("id")
            if rid in seen_ids:
                dropped["duplicate_id_within_batch"] += 1
                continue
            seen_ids.add(rid)
            src = src_index.get(rid) or {}
            if batch == "20261018-P2-r1" and not source_has_content(src):
                dropped["p2_r1_no_content"] += 1
                continue
            if not (row.get("prefilter") or {}).get("release"):
                dropped["not_released"] += 1
                continue
            if not source_has_content(src):
                dropped["no_facts_or_decision"] += 1
                continue
            subject = (row.get("subject_mention") or src.get("subject_mention") or "").strip()
            if not subject:
                no_subject.append({**row, "source_id": rid, "source_batch": batch})
                dropped["no_subject"] += 1
                continue
            doc_key = (src.get("doc_no_hash") or row.get("doc_no_hash")
                       or row.get("text_orig_sha256") or rid or "")
            event_id, event_source = event_id_for(row, src, channel)
            candidates.append({
                "row": row, "src": src, "channel": channel, "batch": batch,
                "subject": subject, "doc_key": doc_key,
                "event_id": event_id, "event_source": event_source,
                "priority": PRIORITY.get(batch, 99),
                "salvage": batch == "20261018-P2-r1",
            })

    # Page/person dedup first, then event/person dedup. Priority keeps the
    # newest canonical source; ties are deterministic by batch/id.
    candidates.sort(key=lambda c: (c["priority"], c["batch"], str(c["row"].get("id"))))
    page_seen = set()
    event_seen = set()
    kept: list[dict] = []
    for c in candidates:
        row, src = c["row"], c["src"]
        subject_key = c["subject"] or f"id:{row.get('id')}"
        page_key = (c["channel"], c["doc_key"], subject_key)
        event_person_key = (c["event_id"], subject_key)
        if page_key in page_seen:
            dropped["duplicate_page_person"] += 1
            continue
        page_seen.add(page_key)
        if event_person_key in event_seen:
            dropped["duplicate_event_person"] += 1
            continue
        event_seen.add(event_person_key)
        new_id = "S1-" + sha(f"{c['event_id']}|{subject_key}|{row.get('id')}")[:20]
        out = dict(row)
        out["id"] = new_id
        out["source_id"] = row.get("id")
        out["source_batch"] = c["batch"]
        out["event_id"] = c["event_id"]
        out["event_key_source"] = c["event_source"]
        out["split"] = split_for(c["event_id"])
        out["grade"] = "A-salvage" if c["salvage"] else "A"
        out["salvage"] = c["salvage"]
        out["party_available"] = bool((src.get("text_party") or "").strip())
        out["text_party"] = src.get("text_party") or ""
        out["party_span"] = (src.get("segments") or {}).get("text_party")
        out["dedup_key"] = list(event_person_key)
        kept.append(out)

    kept_ids = {r["id"] for r in kept}
    if len(kept_ids) != len(kept):
        raise RuntimeError("generated_ids_not_unique")
    events: dict[str, dict] = {}
    for r in kept:
        e = events.setdefault(r["event_id"], {
            "event_id": r["event_id"], "split": r["split"],
            "records": 0, "source_batches": set(), "event_key_source": r["event_key_source"],
        })
        e["records"] += 1
        e["source_batches"].add(r["source_batch"])
        if e["split"] != r["split"]:
            raise RuntimeError("event_crosses_split")
    for e in events.values():
        e["source_batches"] = sorted(e["source_batches"])

    out_records = args.out / "records.jsonl"
    out_records.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), "utf-8")
    out_nosubject = args.out / "no_subject.jsonl"
    out_nosubject.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in no_subject), "utf-8")
    out_events = args.out / "events.jsonl"
    out_events.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events.values()), "utf-8")

    by_grade = Counter(r["grade"] for r in kept)
    by_channel = Counter(r["source_batch"].split("/")[0] if "/" in r["source_batch"] else
                         ("web" if r["source_batch"].startswith("2026") and "web" in r["source_batch"] else "pkulaw")
                         for r in kept)
    by_split = Counter(r["split"] for r in kept)
    by_batch = Counter(r["source_batch"] for r in kept)
    manifest = {
        "version": VERSION,
        "refresh_root": str(args.refresh_root.resolve()),
        "source_root": str(args.source_root.resolve()),
        "catalog_sha256": sha((args.refresh_root / "CATALOG.json").read_text("utf-8")),
        "records": len(kept),
        "no_subject_records": len(no_subject),
        "events": len(events),
        "by_grade": dict(by_grade),
        "by_channel": dict(by_channel),
        "by_split": dict(by_split),
        "by_batch": dict(by_batch),
        "party_available": sum(1 for r in kept if r["party_available"]),
        "dropped": dict(dropped),
        "records_sha256": sha(out_records.read_text("utf-8")),
        "no_subject_sha256": sha(out_nosubject.read_text("utf-8")),
        "events_sha256": sha(out_events.read_text("utf-8")),
    }
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    lines = [
        "# S1 输入去重/事件归并报告",
        "",
        f"- refresh: `{manifest['refresh_root']}`",
        f"- source: `{manifest['source_root']}`",
        f"- label-ready records: **{len(kept)}**; events: **{len(events)}**",
        f"- no-subject records (separate): **{len(no_subject)}**",
        f"- grade: {dict(by_grade)}",
        f"- channel: {dict(by_channel)}",
        f"- split: {dict(by_split)}",
        f"- party_available: {manifest['party_available']}",
        f"- dropped: {dict(dropped)}",
        "",
        "## 规则",
        "",
        "- 主批次 A：canonical + release + 有 facts/decision；P2-r1 仅 salvage（去重后仍有 facts/decision 的记录）。",
        "- 先按 `(channel, doc_key, subject)` 去重来源页/人；再按 `(event_id, subject)` 去重事件/人。",
        "- `event_id` 优先源 `event_key`；缺失时用 doc_no_hash/text_sha 的稳定哈希。",
        "- 每个 event 按哈希分 train/valid/test；同一事件不跨 split。",
        "- 多人事件保留每人一条记录；不把多人折叠成一条。",
        "",
        "## 批次",
        "",
        "| batch | records |",
        "|---|---:|",
    ]
    for b, n in sorted(by_batch.items()):
        lines.append(f"| {b} | {n} |")
    (args.out / "DEDUP_REPORT.md").write_text("\n".join(lines) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in ("records", "events", "by_grade", "by_split", "party_available", "dropped")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

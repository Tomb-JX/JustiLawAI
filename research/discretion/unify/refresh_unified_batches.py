"""Re-materialize every parsed-1 batch into a fresh unified_raw tree.

This is a batch refresh utility, not a new parser:
- source `parsed/<channel>/<batch>/records.jsonl` is read-only;
- output goes to `$DATA/unified_raw_refresh/<date>/<channel>/<batch>/`;
- canonical current batches are listed explicitly; all other batches are still
  converted and marked historical/superseded for audit, not silently discarded.

Run:
  python -B research/discretion/unify/refresh_unified_batches.py \
      --source-root $DATA/parsed \
      --out-root $DATA/unified_raw_refresh/20261018 \
      [--only 20261018-P1-r6,20261017-web-r3]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from to_unified import convert  # noqa: E402

VERSION = "unified-refresh-1"
CANONICAL = {
    "web": {"20261018-web-r4-table-repair"},
    "pkulaw": {
        "20261018-P1-r6",
        "20261018-P1b-r2",
        "20261018-P2-r1",
        "20261018-P2-L4word",
        "merged-20261017-full",
        # 2026-10-26 扩产（负责人指令）：P3–P7 定向采集批入 canonical 供给；
        # 增量构建走 p3p7-additions 合并器，旧 3,194 条 cohort 不动（B-12 版本冻结）。
        "20261021-P3-r1",
        "20261021-P4-r1",
        "20261021-P5-r1",
        "20261021-P6-r1",
        "20261021-P7-r1",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def audit_source(rows: list[dict]) -> dict:
    def count(key: str) -> int:
        return sum(1 for row in rows if (row.get(key) or "").strip())

    facts = count("text_facts")
    decision = count("text_decision")
    union = sum(1 for row in rows if (row.get("text_facts") or "").strip()
                or (row.get("text_decision") or "").strip())
    both = sum(1 for row in rows if (row.get("text_facts") or "").strip()
               and (row.get("text_decision") or "").strip())
    return {
        "records": len(rows),
        "text_party": count("text_party"),
        "text_facts": facts,
        "text_decision": decision,
        "facts_or_decision": union,
        "facts_and_decision": both,
        "outcome_type": sum(1 for row in rows if (row.get("outcome") or {}).get("type")),
    }


def audit_output(out_dir: Path, source_rows: list[dict]) -> dict:
    records_path = out_dir / "records.jsonl"
    rows = read_rows(records_path)
    source_by_id = {row.get("id"): row for row in source_rows}
    forms = Counter(row.get("form") or "(empty)" for row in rows)
    released = sum(1 for row in rows if (row.get("prefilter") or {}).get("release"))
    empty_text = sum(1 for row in rows if not (row.get("cleaned_text") or "").strip())
    empty_sentences = sum(1 for row in rows if not (row.get("sentences") or []))
    bad_sha = sum(1 for row in rows if len(row.get("text_orig_sha256") or "") != 64)
    ids = [row.get("id") for row in rows]
    duplicate_ids = len(ids) - len(set(ids))
    unique_ids = set(ids)
    content_ids = {
        rid for rid in unique_ids
        if (src := source_by_id.get(rid))
        and ((src.get("text_facts") or "").strip() or (src.get("text_decision") or "").strip())
    }
    l5_ids = {
        rid for rid in unique_ids
        if (src := source_by_id.get(rid)) and (src.get("text_facts") or "").strip()
    }
    released_ids = {row.get("id") for row in rows if (row.get("prefilter") or {}).get("release")}
    released_content_ids = {
        rid for rid in released_ids
        if (src := source_by_id.get(rid))
        and ((src.get("text_facts") or "").strip() or (src.get("text_decision") or "").strip())
    }
    released_l5_ids = {
        rid for rid in released_ids
        if (src := source_by_id.get(rid)) and (src.get("text_facts") or "").strip()
    }
    stats = json.loads((out_dir / "stats.json").read_text("utf-8"))
    replay_failures = int(stats.get("replay_failures") or 0)
    format_ok = replay_failures == 0 and empty_text == 0 and empty_sentences == 0 \
        and bad_sha == 0 and duplicate_ids == 0
    notes = []
    if duplicate_ids:
        notes.append(f"duplicate_ids:+{duplicate_ids}")
    if not format_ok:
        notes.append("format_not_ok")
    if source_rows and sum(1 for r in source_rows if (r.get("text_party") or "").strip()) == 0:
        notes.append("no_party_segment")
    if source_rows and len(content_ids) < len(source_rows) * 0.5:
        notes.append("sparse_facts_decision")
    return {
        "records": len(rows),
        "released": released,
        "forms": dict(forms),
        "empty_text": empty_text,
        "empty_sentences": empty_sentences,
        "bad_sha": bad_sha,
        "duplicate_ids": duplicate_ids,
        "replay_failures": replay_failures,
        "format_ok": format_ok,
        "content_records": len(content_ids),
        "l5_ready_records": len(l5_ids),
        "released_content_records": len(released_content_ids),
        "released_l5_records": len(released_l5_ids),
        "content_ready": format_ok and len(content_ids) > 0,
        "notes": notes,
        "records_sha256": sha256(records_path),
        "edits_sha256": sha256(out_dir / "edits.rle.jsonl"),
        "stats_sha256": sha256(out_dir / "stats.json"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--only", default="", help="逗号分隔的批次名；默认全部")
    args = ap.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    args.out_root.mkdir(parents=True, exist_ok=True)

    batches: list[tuple[str, Path]] = []
    for channel in ("web", "pkulaw"):
        for path in sorted((args.source_root / channel).glob("*/records.jsonl")):
            batches.append((channel, path))
    if only:
        batches = [(ch, p) for ch, p in batches if p.parent.name in only]

    catalog = {
        "version": VERSION,
        "source_root": str(args.source_root.resolve()),
        "out_root": str(args.out_root.resolve()),
        "canonical": {k: sorted(v) for k, v in CANONICAL.items()},
        "batches": [],
    }
    for channel, src in batches:
        batch = src.parent.name
        out_dir = args.out_root / channel / batch
        entry = {"channel": channel, "batch": batch, "source": str(src)}
        try:
            source_rows = read_rows(src)
            entry["source_audit"] = audit_source(source_rows)
            stats = convert(str(src), channel, str(out_dir))
            entry["stats"] = stats
            entry["output"] = audit_output(out_dir, source_rows)
            entry["canonical"] = batch in CANONICAL.get(channel, set())
        except Exception as exc:  # keep converting other batches; record the failure
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["canonical"] = batch in CANONICAL.get(channel, set())
        catalog["batches"].append(entry)

    total_records = sum(b.get("output", {}).get("records", 0) for b in catalog["batches"])
    format_ok = sum(b.get("output", {}).get("records", 0) for b in catalog["batches"]
                    if b.get("output", {}).get("format_ok"))
    content_ready = sum(b.get("output", {}).get("content_records", 0) for b in catalog["batches"]
                        if b.get("output", {}).get("content_ready"))
    released_content = sum(b.get("output", {}).get("released_content_records", 0) for b in catalog["batches"]
                           if b.get("canonical") and b.get("output", {}).get("format_ok"))
    released_l5 = sum(b.get("output", {}).get("released_l5_records", 0) for b in catalog["batches"]
                      if b.get("canonical") and b.get("output", {}).get("format_ok"))
    canonical_records = sum(b.get("output", {}).get("records", 0) for b in catalog["batches"]
                            if b.get("canonical"))
    catalog["summary"] = {
        "batches": len(catalog["batches"]),
        "errors": sum(1 for b in catalog["batches"] if b.get("error")),
        "records": total_records,
        "format_ok_records": format_ok,
        "content_ready_records": content_ready,
        "canonical_records": canonical_records,
        "canonical_released_content_records": released_content,
        "canonical_released_l5_records": released_l5,
    }
    (args.out_root / "CATALOG.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )

    lines = [
        "# unified_raw refresh audit",
        "",
        f"- source: `{catalog['source_root']}`",
        f"- out: `{catalog['out_root']}`",
        f"- batches: {catalog['summary']['batches']} (errors {catalog['summary']['errors']})",
        f"- records: {catalog['summary']['records']}; format_ok records: {catalog['summary']['format_ok_records']}; "
        f"content_ready records: {catalog['summary']['content_ready_records']}; canonical records: {catalog['summary']['canonical_records']}",
        "",
        "| channel | batch | n | format_ok | content_ready | party | facts | decision | canonical | notes | error |",
        "|---|---|---:|---|---|---:|---:|---:|---|---|---|",
    ]
    for b in catalog["batches"]:
        out = b.get("output") or {}
        src = b.get("source_audit") or {}
        lines.append(
            f"| {b['channel']} | {b['batch']} | {out.get('records', 0)} | "
            f"{out.get('format_ok', False)} | {out.get('content_ready', False)} | "
            f"{src.get('text_party', 0)} | {src.get('text_facts', 0)} | "
            f"{src.get('text_decision', 0)} | {b.get('canonical', False)} | "
            f"{', '.join(out.get('notes', []))} | {b.get('error', '')} |"
        )
    (args.out_root / "REPORT.md").write_text("\n".join(lines) + "\n", "utf-8")
    print(json.dumps(catalog["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

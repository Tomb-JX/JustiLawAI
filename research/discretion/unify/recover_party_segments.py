"""Recover `text_party` for parsed batches where the field is empty.

The recovery is deliberately conservative and source-grounded:
- only extracts a contiguous substring of `text_full`;
- prefers a sentence/line that starts with a party role
  (违法行为人/被处罚人/当事人/行政相对人) and contains identity markers;
- rejects penalty/decision language;
- writes a new parsed batch tree; never mutates the source batch.

Output:
  $DATA/parsed_refresh/20261018/<channel>/<batch>/records.jsonl
  $DATA/parsed_refresh/20261018/PARTY_RECOVERY_REPORT.md
  $DATA/parsed_refresh/20261018/MANIFEST.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

VERSION = "party-recovery-1"
ROLE = re.compile(r"(?:违法行为人|被处罚人|当事人|行政相对人|被侵害人)")
IDENTITY = re.compile(r"(?:男|女)[，,、\s]|(?:\d{1,3}|[一二三四五六七八九十百]+)岁|出生|住址|现住|户籍|身份证|民族|文化|无违法犯罪|工作单位|职业")
BAD = re.compile(r"决定(?:给予|予以|如下)|罚款|拘留|没收|依据|根据《|第[零〇一二三四五六七八九十百\d]+条")
STRONG_IDENTITY = re.compile(r"出生|身份证|户籍|现住|文化|民族")
ROLE_NAMES = r"(?:违法行为人|被处罚人|当事人|行政相对人|相对人)"
TABLE_ROLE = re.compile(rf"^{ROLE_NAMES}(?:名称)?\s*(?:[：:]|\|)\s*(.*)$")
TABLE_LABEL = re.compile(rf"^{ROLE_NAMES}(?:名称)?\s*$")
TABLE_INLINE = re.compile(rf"^{ROLE_NAMES}(?:名称)?\s+([^\s]{{1,20}})$")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def candidate_lines(text: str) -> list[tuple[int, int, str, str]]:
    out = []
    lines = text.splitlines(keepends=True)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append((offset, offset + len(line)))
        offset += len(line)
    for idx, line in enumerate(lines):
        start, end = offsets[idx]
        body = line.strip()
        if not body:
            continue
        lead = len(line) - len(line.lstrip())
        trimmed_start, trimmed_end = start + lead, start + lead + len(body)
        table = TABLE_ROLE.match(body)
        inline = TABLE_INLINE.match(body)
        label = TABLE_LABEL.match(body)
        if table:
            value = (table.group(1) or "").strip()
            if value:
                out.append((trimmed_start, trimmed_end, body, "table_line"))
                continue
            label = True
        if inline:
            out.append((trimmed_start, trimmed_end, body, "table_line"))
            continue
        if label:
            # Label-only line: take the next non-empty line as the value.
            for j in range(idx + 1, len(lines)):
                nxt = lines[j].strip()
                if not nxt:
                    continue
                nstart, _ = offsets[j]
                nlead = len(lines[j]) - len(lines[j].lstrip())
                value_start = nstart + nlead
                value_end = value_start + len(nxt)
                out.append((trimmed_start, value_end, text[trimmed_start:value_end], "table_line"))
                break
            continue
        if ROLE.search(body) and IDENTITY.search(body):
            out.append((trimmed_start, trimmed_end, body, "party_sentence"))
    return out


def recover(rec: dict) -> tuple[str | None, int, int, str]:
    if (rec.get("text_party") or "").strip():
        return None, -1, -1, "existing"
    text = rec.get("text_full") or ""
    if not text:
        return None, -1, -1, "empty_text"
    facts = (rec.get("segments") or {}).get("text_facts")
    facts_start = facts[0] if isinstance(facts, list) and len(facts) == 2 else None
    for start, end, body, method in candidate_lines(text):
        # Table forms often have text_facts starting at the document head; the
        # party label is part of the table header, so only apply the bound when
        # facts start after the header.
        if facts_start is not None and facts_start > 0 and start >= facts_start:
            continue
        if BAD.search(body):
            # A party sentence can contain a prior-penalty clause ("违法经历…
            # 行政拘留"); keep it only when it starts with the role and has
            # strong identity markers. Penalty-summary lines do not.
            if not (method == "party_sentence" and ROLE.match(body)
                    and STRONG_IDENTITY.search(body)):
                continue
        # Normalize whitespace for length/quality checks, but keep the original span.
        if len(body) < 2 or len(body) > 600:
            continue
        if method == "table_line" and len(body) > 200:
            continue
        quote = text[start:end]
        # Ensure the returned span is exactly the source text.
        if quote != text[start:end]:
            continue
        return quote, start, end, method
    return None, -1, -1, "unrecovered"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--batches", default="", help="逗号分隔 batch 名；默认全部")
    args = ap.parse_args()
    only = {x.strip() for x in args.batches.split(",") if x.strip()}
    args.out_root.mkdir(parents=True, exist_ok=True)
    manifest = {"version": VERSION, "source_root": str(args.source_root.resolve()),
                "out_root": str(args.out_root.resolve()), "batches": []}
    for channel in ("web", "pkulaw"):
        for src in sorted((args.source_root / channel).glob("*/records.jsonl")):
            batch = src.parent.name
            if only and batch not in only:
                continue
            records = rows(src)
            counts = Counter()
            repaired = []
            for rec in records:
                out = dict(rec)
                quote, start, end, method = recover(rec)
                counts[method] += 1
                if quote is not None:
                    out["text_party"] = quote
                    segments = dict(out.get("segments") or {})
                    segments["text_party"] = [start, end]
                    out["segments"] = segments
                    out["party_recovery"] = {"method": method, "start": start, "end": end}
                else:
                    out["party_recovery"] = {"method": method}
                repaired.append(out)
            dst = args.out_root / channel / batch / "records.jsonl"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in repaired), "utf-8")
            session = {"channel": channel, "batch": batch, "records": len(records),
                       "counts": dict(counts), "sha256": sha(dst.read_text("utf-8"))}
            manifest["batches"].append(session)
    (args.out_root / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    lines = ["# party segment recovery", "", "| channel | batch | records | existing | recovered sentence | recovered table | unrecovered |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for b in manifest["batches"]:
        c = b["counts"]
        lines.append(f"| {b['channel']} | {b['batch']} | {b['records']} | {c.get('existing',0)} | "
                     f"{c.get('party_sentence',0)} | {c.get('table_line',0)} | {c.get('unrecovered',0)} |")
    (args.out_root / "PARTY_RECOVERY_REPORT.md").write_text("\n".join(lines) + "\n", "utf-8")
    print(json.dumps({"batches": len(manifest["batches"]),
                      "records": sum(b["records"] for b in manifest["batches"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

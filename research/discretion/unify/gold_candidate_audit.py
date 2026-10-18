"""Offline, conservative audit of narrative L5 material; does not alter S1 release.

Use parsed-1 only as a source-evidence hint. Passing this screen is not a gold label.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def source_page(record_id: str) -> str:
    return re.sub(r"(?<=\d)-(?:d|r|t)?\d+$", "", record_id)


def reasons(unified: dict, parsed: dict | None) -> list[str]:
    out = []
    if unified.get("form") != "叙述式-独立成篇":
        out.append("not_independent_narrative")
    if not (unified.get("prefilter") or {}).get("release"):
        out.append("not_released")
    if not parsed:
        return out + ["missing_parsed_source"]
    if len((parsed.get("text_facts") or "").strip()) < 30:
        out.append("no_located_facts")
    if len((parsed.get("text_decision") or "").strip()) < 12:
        out.append("no_located_decision")
    if not (parsed.get("subject_mention") or "").strip():
        out.append("no_source_subject")
    else:
        subject = parsed["subject_mention"].strip()
        facts = parsed.get("text_facts") or ""
        decision = parsed.get("text_decision") or ""
        if subject not in facts or subject not in decision:
            out.append("subject_not_in_both_spans")
        if facts.count(subject) > 1 and ("*" in subject or "x" in subject.lower()):
            out.append("ambiguous_masked_subject")
    if re.search(r"[Xx＊*]{2,4}[年月日]", parsed.get("text_facts") or ""):
        out.append("masked_behavior_date")
    if not re.search(r"(?:拘留|罚款)[^。；]{0,30}[一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟\d]+(?:日|元)",
                     parsed.get("text_decision") or ""):
        out.append("no_quantified_decision")
    # This is a risk flag, not a definitive topic judgment.
    if not re.search(r"赌博|赌资|赌注|聚赌|以营利为目的.*赌博", parsed.get("text_facts") or ""):
        out.append("facts_without_gambling_evidence")
    return out


def rows(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def audit(unified_path: Path, parsed_path: Path, fixed_outputs: Path, out_path: Path) -> dict:
    parsed = {row["id"]: row for row in rows(parsed_path)}
    excluded_pages = {source_page(row["id"]) for row in rows(fixed_outputs)}
    counts = {"examined": 0, "pass": 0, "excluded_final300_page": 0}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows(unified_path):
            rid = row["id"]
            if source_page(rid) in excluded_pages:
                counts["excluded_final300_page"] += 1
                continue
            flags = reasons(row, parsed.get(rid))
            counts["examined"] += 1
            if not flags:
                counts["pass"] += 1
            stream.write(json.dumps({"id": rid, "source_page": source_page(rid),
                                     "candidate": not flags, "reasons": flags}, ensure_ascii=False) + "\n")
    return counts


def main():
    parser = argparse.ArgumentParser()
    for name in ("unified", "parsed", "fixed_outputs", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.unified, args.parsed, args.fixed_outputs, args.out), ensure_ascii=False))


if __name__ == "__main__":
    main()

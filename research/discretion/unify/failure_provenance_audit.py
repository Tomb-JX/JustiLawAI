"""Join fixed S3 failures to parsed/S0 and harvested page evidence, read-only inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gold_candidate_audit import rows, source_page


def audit(findings: Path, parsed: Path, unified: Path, pages: Path, out: Path) -> dict:
    parsed_by_id = {row["id"]: row for row in rows(parsed)}
    unified_by_id = {row["id"]: row for row in rows(unified)}
    pages_by_id = {}
    for page in rows(pages):
        if page.get("manifest_id"):
            pages_by_id.setdefault(page["manifest_id"], page)
    failures = [row for row in rows(findings) if row["status"] == "error"]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as stream:
        for failure in failures:
            rid = failure["id"]
            original = parsed_by_id.get(rid) or {}
            clean = unified_by_id.get(rid) or {}
            page = pages_by_id.get(source_page(rid)) or {}
            record = {
                "id": rid, "checks": [f["check"] for f in failure["findings"] if f["severity"] == "error"],
                "form": clean.get("form"), "source_type": original.get("source_type"),
                "page_url": page.get("url"), "raw_path": page.get("raw_path"),
                "text_path": page.get("text_path"),
                "parsed_facts_len": len(original.get("text_facts") or ""),
                "parsed_decision_len": len(original.get("text_decision") or ""),
                "parsed_text_len": len(original.get("text_full") or ""),
                "s0_text_len": len(clean.get("cleaned_text") or ""),
                "provenance_status": "needs_raw_field_review",
            }
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"failures": len(failures), "with_raw_page": sum(bool(pages_by_id.get(source_page(x["id"]))) for x in failures),
            "with_parsed_record": sum(x["id"] in parsed_by_id for x in failures),
            "with_s0_record": sum(x["id"] in unified_by_id for x in failures)}


def main():
    parser = argparse.ArgumentParser()
    for name in ("findings", "parsed", "unified", "pages", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.findings, args.parsed, args.unified, args.pages, args.out), ensure_ascii=False))


if __name__ == "__main__":
    main()

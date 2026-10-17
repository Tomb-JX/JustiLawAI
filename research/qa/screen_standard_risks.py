"""Hash-bound metadata-only screen for unresolved annotation standard cases.

Usage: python screen_standard_risks.py <candidate_manifest.json>
       <delivery.jsonl> <output.json>
This is recall-oriented triage, not a semantic or legal decision.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

NUMBER = r"(?:\d+(?:\.\d+)?\s*[万千百]?|[一二三四五六七八九十百千万]+)"
OPEN_AMOUNT = re.compile(
    rf"{NUMBER}\s*元\s*(?:以上|以下|起|及以上)|"
    rf"(?:不少于|不低于|超过|大于|至少)\s*{NUMBER}\s*元"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    manifest_path, source_path, out = map(Path, argv[1:])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_bytes = source_path.read_bytes()
    if sha(source_bytes) != manifest["delivery_file_sha256"]:
        raise SystemExit("Delivery hash differs from candidate manifest")
    wanted = {item["id"]: item for item in manifest["entries"]}
    found = {}
    for line in source_bytes.decode("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rid = row.get("id")
            if rid in wanted:
                if rid in found:
                    raise SystemExit("Duplicate candidate ID")
                if sha((row.get("text_full") or "").encode("utf-8")) != wanted[rid]["text_sha256"]:
                    raise SystemExit("Candidate record hash mismatch")
                facts = row.get("text_facts") or ""
                found[rid] = {
                    "id": rid, "text_sha256": wanted[rid]["text_sha256"],
                    "codes": ["open_amount_phrase_candidate"] if OPEN_AMOUNT.search(facts) else [],
                    "profit_purpose_explicit_phrase_in_facts": "以营利为目的" in facts,
                    "fee_mechanism_keyword_in_facts": any(
                        token in facts for token in ("抽头", "台费", "水钱", "收费")),
                }
    if set(found) != set(wanted):
        raise SystemExit("Candidate record missing from delivery")
    report = {
        "source_version": manifest["delivery"],
        "source_file_sha256": sha(source_bytes),
        "scope": "regex_triage_only_not_field_decision",
        "n_candidate": len(found),
        "n_open_amount_phrase_candidates": sum(bool(item["codes"]) for item in found.values()),
        "records": [found[rid] for rid in sorted(found) if found[rid]["codes"]],
        "n_profit_phrase_in_facts": sum(item["profit_purpose_explicit_phrase_in_facts"]
                                        for item in found.values()),
        "n_fee_keyword_in_facts": sum(item["fee_mechanism_keyword_in_facts"]
                                     for item in found.values()),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "source_version", "n_candidate", "n_open_amount_phrase_candidates",
        "n_profit_phrase_in_facts", "n_fee_keyword_in_facts")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

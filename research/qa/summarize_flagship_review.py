"""Export a metadata-only triage summary; never copy source or model prose."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

from flagship_client import REVIEW_TRIO

ASPECTS = ("privacy", "subject", "facts", "event")


def load(path: Path) -> dict[str, dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if item["id"] in rows:
                raise ValueError("Duplicate review ID")
            rows[item["id"]] = item
    return rows


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("Usage: summarize_flagship_review.py <candidate_manifest> <run_dir> <compiled_dir> <new_repo_output_dir>")
        return 2
    candidate_path, run_dir, compiled_dir, out = map(Path, argv[1:])
    repo = Path(__file__).resolve().parents[2]
    if not out.resolve().is_relative_to(repo) or out.exists():
        raise SystemExit("Summary output must be a new directory inside the repository")
    manifest = json.loads(candidate_path.read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in manifest["entries"]}
    if len(entries) != 50:
        raise SystemExit("Expected 50 candidate records")
    rows = {provider: load(run_dir / f"review_{provider}.jsonl") for provider in REVIEW_TRIO}
    if any(set(group) != set(entries) for group in rows.values()):
        raise SystemExit("Review coverage incomplete")
    receipts = load(compiled_dir / "review_receipts.jsonl")
    unresolved = {}
    with (compiled_dir / "unresolved.csv").open(encoding="utf-8-sig", newline="") as handle:
        unresolved = {item["id"]: item["category"] for item in csv.DictReader(handle)}
    if set(receipts) | set(unresolved) != set(entries) or set(receipts) & set(unresolved):
        raise SystemExit("Compiled result coverage mismatch")
    overview = {
        "delivery": manifest["delivery"],
        "delivery_file_sha256": manifest["delivery_file_sha256"],
        "candidate_count": len(entries),
        "receipts_closed": len(receipts),
        "unresolved": len(unresolved),
        "unresolved_categories": dict(Counter(unresolved.values())),
        "providers": {},
    }
    for provider, group in rows.items():
        valid = [item for item in group.values() if item.get("status") == "valid_review"]
        overview["providers"][provider] = {
            "model": valid[0]["requested_model"] if valid else None,
            "valid_review": len(valid),
            "invalid_review": len(group) - len(valid),
            "error_types": dict(Counter(item.get("error_type") for item in group.values()
                                        if item.get("status") != "valid_review")),
            "aspects": {aspect: dict(Counter(item["answer"][aspect] for item in valid))
                        for aspect in ASPECTS},
            "issue_codes": dict(Counter(code for item in valid
                                        for code in item["answer"]["issue_codes"])),
        }
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_text(json.dumps(overview, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    columns = ["id", "version", "text_sha256", "event_id", "result"]
    for provider in REVIEW_TRIO:
        columns += [f"{provider}_status", f"{provider}_error_type",
                    f"{provider}_aspects", f"{provider}_issue_codes",
                    f"{provider}_flag_dispositions"]
    with (out / "triage.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for rid in sorted(entries):
            entry = entries[rid]
            item = {"id": rid, "version": entry["version"],
                    "text_sha256": entry["text_sha256"], "event_id": entry["event_id"],
                    "result": "closed" if rid in receipts else unresolved[rid]}
            for provider in REVIEW_TRIO:
                review = rows[provider][rid]
                answer = review.get("answer") or {}
                item[f"{provider}_status"] = review.get("status")
                item[f"{provider}_error_type"] = review.get("error_type") or ""
                item[f"{provider}_aspects"] = ";".join(
                    f"{aspect}:{answer[aspect]}" for aspect in ASPECTS if aspect in answer)
                item[f"{provider}_issue_codes"] = ";".join(answer.get("issue_codes") or [])
                item[f"{provider}_flag_dispositions"] = ";".join(
                    f"{flag}:{status}" for flag, status in
                    sorted((answer.get("flag_dispositions") or {}).items()))
            writer.writerow(item)
    print(json.dumps({"receipts_closed": len(receipts), "unresolved": len(unresolved),
                      "output": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

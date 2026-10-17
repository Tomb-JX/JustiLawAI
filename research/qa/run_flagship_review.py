"""Run three independent flagship safety reviews against an immutable candidate.

Usage: python run_flagship_review.py --preflight
       python run_flagship_review.py <manifest.json> <delivery.jsonl>
              <record_review_queue.csv> <new_controlled_output_dir>

The output contains model responses and must stay outside the repository.
No safety receipt is issued by this script.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from flagship_client import MODELS, REVIEW_TRIO, call_json, configured

ASPECTS = ("privacy", "subject", "facts", "event")
STATUSES = {"pass", "review", "fail"}
ISSUE_CODES = {
    "possible_person_name": "privacy", "other_person_identifier": "privacy",
    "contact_or_address": "privacy", "subject_ambiguous": "subject",
    "subject_not_in_facts": "subject", "facts_incomplete": "facts",
    "facts_contains_conclusion": "facts", "event_link_ambiguous": "event",
    "other_uncertainty": None,
}
FLAG_DISPOSITIONS = {"false_positive", "confirmed_issue", "uncertain"}
SYSTEM = (
    "你是独立的旗舰模型案卷安全复检员。只返回 JSON，不引述原文、人名、地址或联系方式。"
    "按完整正文分别核验：隐私脱敏、甲的本人身份与事实段对齐、事实段完整且无结论污染、"
    "事件关联可信度。pass 只用于明确通过；不确定用 review；发现问题用 fail。"
    "issue_codes 只能用给定代码；代码对应的检查项不得同时 pass。"
    "对每个自动信号给出 false_positive、confirmed_issue 或 uncertain。"
    "不要把来源自带的 r6_scan.passed 当作复检结论。"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_answer(answer: dict, flags: list[str]) -> dict:
    if set(answer) != set(ASPECTS) | {"issue_codes", "flag_dispositions"}:
        raise ValueError("Review response keys invalid")
    if any(answer[key] not in STATUSES for key in ASPECTS):
        raise ValueError("Review status invalid")
    codes = answer["issue_codes"]
    if not isinstance(codes, list) or any(code not in ISSUE_CODES for code in codes):
        raise ValueError("Review issue code invalid")
    if any(ISSUE_CODES[code] and answer[ISSUE_CODES[code]] == "pass" for code in codes):
        raise ValueError("Review status contradicts issue code")
    dispositions = answer["flag_dispositions"]
    if (not isinstance(dispositions, dict) or set(dispositions) != set(flags)
            or any(value not in FLAG_DISPOSITIONS for value in dispositions.values())):
        raise ValueError("Automatic flag disposition missing or invalid")
    if any(value == "confirmed_issue" for value in dispositions.values()) and all(
            answer[key] == "pass" for key in ASPECTS):
        raise ValueError("Confirmed issue contradicts all-pass review")
    return answer


def main(argv: list[str]) -> int:
    if argv[1:] == ["--preflight"]:
        print(json.dumps({provider: {"model": MODELS[provider][0], "configured": configured(provider)}
                          for provider in REVIEW_TRIO}))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default=",".join(REVIEW_TRIO))
    parser.add_argument("--prompt-keys", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-invalid", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("queue", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv[1:])
    providers = args.providers.split(",")
    if not providers or len(set(providers)) != len(providers) or any(p not in REVIEW_TRIO for p in providers):
        parser.error("--providers must contain distinct approved provider names")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be from 1 to 8")
    if not 30 <= args.timeout <= 600 or (args.retry_invalid and not args.resume):
        parser.error("--timeout must be 30..600 and --retry-invalid requires --resume")
    manifest_path, source_path, queue_path, out = (
        args.manifest, args.source, args.queue, args.output)
    repo = Path(__file__).resolve().parents[2]
    if out.resolve().is_relative_to(repo) or (out.exists() and not args.resume) or (
        args.resume and not out.is_dir()
    ):
        raise SystemExit("Output must be a controlled directory outside repository; use --resume to continue")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_bytes = source_path.read_bytes()
    if sha(source_bytes) != manifest["delivery_file_sha256"]:
        raise SystemExit("Delivery hash differs from candidate manifest")
    entries = {entry["id"]: entry for entry in manifest["entries"]}
    if len(entries) != 50:
        raise SystemExit("Expected 50 distinct candidate IDs")
    with queue_path.open(encoding="utf-8-sig", newline="") as handle:
        queue = {item["id"]: item for item in csv.DictReader(handle)}
    if set(queue) != set(entries):
        raise SystemExit("Review queue IDs differ from candidate")
    records = {}
    for line in source_bytes.decode("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("id") in entries:
                records[row["id"]] = row
    if set(records) != set(entries):
        raise SystemExit("Candidate IDs missing from delivery")
    for rid, row in records.items():
        if sha((row.get("text_full") or "").encode("utf-8")) != entries[rid]["text_sha256"]:
            raise SystemExit("Candidate text hash mismatch")
    run_manifest = {
        "scope": "flagship_record_level_review_not_human_verification",
        "delivery": manifest["delivery"], "delivery_file_sha256": sha(source_bytes),
        "candidate_manifest_sha256": sha(manifest_path.read_bytes()),
        "queue_sha256": sha(queue_path.read_bytes()),
        "system_prompt_sha256": sha(SYSTEM.encode("utf-8")),
        "models": {p: MODELS[p][0] for p in REVIEW_TRIO},
    }
    if args.resume:
        if json.loads((out / "run_manifest.json").read_text(encoding="utf-8")) != run_manifest:
            raise SystemExit("Existing review run does not match source, queue, prompt or models")
    else:
        out.mkdir(parents=True, exist_ok=False)
        (out / "run_manifest.json").write_text(
            json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    created_keys = []
    try:
      if args.prompt_keys:
        for provider in providers:
            name = MODELS[provider][1]
            if not os.getenv(name):
                os.environ[name] = getpass.getpass(f"{provider} API key: ")
                created_keys.append(name)
      missing = [provider for provider in providers if not configured(provider)]
      if missing:
          raise SystemExit("Flagship credentials unavailable for: " + ", ".join(missing))
      invalid_count = 0
      for provider in providers:
        review_file = out / f"review_{provider}.jsonl"
        prior = {}
        if args.resume and review_file.exists():
            for line in review_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    rid = item["id"]
                    if rid in prior or rid not in entries or item.get("provider") != provider or (
                        item.get("text_sha256") != entries[rid]["text_sha256"]
                    ):
                        raise SystemExit("Existing provider review file is invalid")
                    prior[rid] = item
            if args.retry_invalid:
                retry = [item for item in prior.values() if item.get("status") != "valid_review"]
                if retry:
                    history = out / f"retry_history_{provider}.jsonl"
                    with history.open("a", encoding="utf-8", newline="\n") as handle:
                        for item in retry:
                            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                    prior = {rid: item for rid, item in prior.items()
                             if item.get("status") == "valid_review"}
                    temp = review_file.with_suffix(".rewrite")
                    with temp.open("x", encoding="utf-8", newline="\n") as handle:
                        for item in prior.values():
                            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                    temp.replace(review_file)
            invalid_count += sum(item.get("status") != "valid_review" for item in prior.values())
        def review_one(rid: str) -> dict:
            row = records[rid]
            flags = sorted(filter(None, queue[rid]["automatic_flags"].split(";")))
            user = json.dumps({
                "id": rid, "event_id": row.get("event_id"),
                "subject_alias": row.get("subject_alias"), "text_facts": row.get("text_facts"),
                "text_full": row.get("text_full"), "automatic_flags": flags,
                "required_json": {key: "pass|review|fail" for key in ASPECTS} | {
                    "issue_codes": sorted(ISSUE_CODES),
                    "flag_dispositions": {flag: "false_positive|confirmed_issue|uncertain" for flag in flags}},
            }, ensure_ascii=False)
            item = {"id": rid, "event_id": entries[rid]["event_id"],
                    "text_sha256": entries[rid]["text_sha256"],
                    "version": manifest["delivery"], "provider": provider,
                    "requested_model": MODELS[provider][0],
                    "request_sha256": sha((SYSTEM + "\n" + user).encode("utf-8")),
                    "reviewed_at": datetime.now(timezone.utc).isoformat()}
            try:
                response = call_json(provider, SYSTEM, user, timeout=args.timeout)
                validate_answer(response["answer"], flags)
                item.update({"returned_model": response["returned_model"],
                             "response_id": response["response_id"],
                             "answer": response["answer"], "status": "valid_review"})
            except Exception as exc:
                item.update({"status": "invalid_review", "error_type": type(exc).__name__})
            return item

        remaining = [rid for rid in sorted(entries) if rid not in prior]
        with review_file.open("a" if args.resume else "x", encoding="utf-8", newline="\n") as handle:
          with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for item in pool.map(review_one, remaining):
                if item["status"] != "valid_review":
                    invalid_count += 1
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
                print(json.dumps({"id": item["id"], "provider": provider,
                                  "status": item["status"]}), flush=True)
    finally:
        for name in created_keys:
            os.environ.pop(name, None)
    return 1 if invalid_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Auditably replace the uncalled GPT plan with Kimi in an existing review run.

The existing DeepSeek and Qwen calls remain bound to their original hashes.
No source text or API key is read by this migration.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from flagship_client import MODELS, REVIEW_TRIO


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("Usage: adopt_kimi_review.py <manifest.json> <queue.csv> <review_run_dir>")
        return 2
    manifest_path, queue_path, run_dir = map(Path, argv[1:])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in manifest["entries"]}
    old_path = run_dir / "run_manifest.json"
    old_bytes = old_path.read_bytes()
    old = json.loads(old_bytes)
    expected_old = {p: MODELS[p][0] for p in ("deepseek", "qwen", "openai")}
    if (old.get("models") != expected_old
            or old.get("candidate_manifest_sha256") != sha(manifest_path.read_bytes())
            or old.get("queue_sha256") != sha(queue_path.read_bytes())
            or old.get("delivery_file_sha256") != manifest["delivery_file_sha256"]
            or len(entries) != 50):
        raise SystemExit("Existing plan does not match the frozen candidate or old model trio")
    if any((run_dir / f"review_{p}.jsonl").exists() for p in ("openai", "kimi")):
        raise SystemExit("Third-model results already exist; migration refused")
    for provider in ("deepseek", "qwen"):
        rows = [json.loads(line) for line in
                (run_dir / f"review_{provider}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        if (len(rows) != 50 or {item["id"] for item in rows} != set(entries)
                or any(item.get("provider") != provider
                       or item.get("requested_model") != MODELS[provider][0]
                       or item.get("text_sha256") != entries[item["id"]]["text_sha256"]
                       or item.get("event_id") != entries[item["id"]]["event_id"]
                       or item.get("version") != entries[item["id"]]["version"]
                       for item in rows)):
            raise SystemExit("Existing review results have incomplete or mismatched coverage")
    archive = run_dir / "run_manifest_before_kimi.json"
    change = run_dir / "model_policy_change.json"
    if archive.exists() or change.exists():
        raise SystemExit("Migration already attempted")
    archive.write_bytes(old_bytes)
    new = dict(old)
    new["models"] = {p: MODELS[p][0] for p in REVIEW_TRIO}
    new_bytes = (json.dumps(new, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    old_path.write_bytes(new_bytes)
    change.write_text(json.dumps({
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "reason": "user_authorized_heterogeneous_bailian_third_model",
        "uncalled_provider_replaced": "openai",
        "selected_provider": "kimi",
        "old_manifest_sha256": sha(old_bytes),
        "new_manifest_sha256": sha(new_bytes),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "third_model_plan_updated", "reviewed_existing_records": 50,
                      "selected_model": MODELS["kimi"][0]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""A/B/C blind extraction on a frozen, reviewed pilot50-safe subset.

Usage: python run_flagship_blind_annotation.py <safe_manifest.json>
       <pilot50-safe.jsonl> <annotation-guideline.md> <new_controlled_output_dir>

Each flagship sees the same immutable protocol and party/facts text, never another
model's answers. This stage does not arbitrate or declare a completed gold set.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from flagship_client import MODELS, call_json, configured
from validate_annotations import FIELD_TYPES, STATUSES

ROLES = {"A": "deepseek", "B": "qwen", "C": "kimi"}
SYSTEM = (
    "你是行政赌博案卷要素标注员。严格按协议逐字段独立标注，只输出 JSON 对象，"
    "顶层仅有 fields，包含全部指定字段。每字段为 {status,value,evidence}；"
    "status 为 明确、推断、未提及；未提及的 value=null 且 evidence=[]。"
    "有值必须提供从所给当事人信息或事实段逐字复制的连续证据列表。"
    "不得使用处罚结果、说理、法条或其他模型的答案推断事实。"
    "开放金额上界按指南记 max:null；主体冲突、模糊日期无法解决时留为未提及，不要虚构。"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def protocol_from_guide(text: str) -> str:
    start = text.index("## 1. 总原则")
    end = text.index("## 5. 质量控制", start)
    return text[start:end]


def party_and_facts(row: dict) -> tuple[str, str]:
    full = row.get("text_full") or ""
    facts = row.get("text_facts") or ""
    segment = (row.get("segments") or {}).get("text_facts")
    if (not isinstance(segment, list) or len(segment) != 2
            or not all(isinstance(x, int) for x in segment)
            or not 0 <= segment[0] <= segment[1] <= len(full)
            or full[segment[0]:segment[1]] != facts):
        raise ValueError("Facts segment offset invalid")
    return full[:segment[0]], facts


def validate_fields(answer: dict, party: str, facts: str) -> dict:
    if set(answer) != {"fields"} or not isinstance(answer["fields"], dict):
        raise ValueError("Annotation response shape invalid")
    fields = answer["fields"]
    if set(fields) != set(FIELD_TYPES):
        raise ValueError("Annotation field coverage invalid")
    for field, item in fields.items():
        if not isinstance(item, dict) or not {"status", "value", "evidence"}.issubset(item):
            raise ValueError("Annotation field shape invalid")
        status, value, evidence = item["status"], item["value"], item["evidence"]
        if status not in STATUSES or not isinstance(evidence, list):
            raise ValueError("Annotation status or evidence type invalid")
        if status == "未提及":
            if value is not None or evidence:
                raise ValueError("Unmentioned field has a value or evidence")
            continue
        if value is None or not evidence or any(
                not isinstance(q, str) or not q or (q not in party and q not in facts)
                for q in evidence):
            raise ValueError("Valued field lacks verbatim input evidence")
        ftype = FIELD_TYPES[field]
        if ftype == "amount":
            if (not isinstance(value, dict) or set(value) != {"min", "max"}
                    or not isinstance(value["min"], (int, float))
                    or isinstance(value["min"], bool) or not math.isfinite(value["min"])
                    or not 0 <= value["min"]
                    or (value["max"] is not None and (
                        not isinstance(value["max"], (int, float))
                        or isinstance(value["max"], bool)
                        or not math.isfinite(value["max"])
                        or value["min"] > value["max"]))):
                raise ValueError("Amount value invalid")
        elif ftype == "int" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError("Integer value invalid")
        elif ftype == "float" and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                   or not math.isfinite(value)):
            raise ValueError("Float value invalid")
        elif ftype == "bool" and not isinstance(value, bool):
            raise ValueError("Boolean value invalid")
        elif ftype in ("enum", "date") and not isinstance(value, str):
            raise ValueError("String value invalid")
    return fields


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    manifest_path, input_path, guide_path, out = map(Path, argv[1:])
    missing = [p for p in ROLES.values() if not configured(p)]
    if missing:
        raise SystemExit("Flagship credentials unavailable for: " + ", ".join(missing))
    repo = Path(__file__).resolve().parents[2]
    if out.resolve().is_relative_to(repo) or out.exists():
        raise SystemExit("Output must be a new controlled directory outside repository")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_bytes = input_path.read_bytes()
    if (manifest.get("subset_status") != "record_level_review_pass"
            or manifest.get("review_basis") != "three_flagship_model_unanimous_or_human_review"
            or sha(input_bytes) != manifest.get("input_sha256")
            or manifest.get("n_records") != 50):
        raise SystemExit("Safe subset manifest or input hash invalid")
    rows = [json.loads(line) for line in input_bytes.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != 50 or len({row["id"] for row in rows}) != 50:
        raise SystemExit("Safe subset must have exactly 50 unique records")
    records = {item["id"]: item for item in manifest["records"]}
    if set(records) != {row["id"] for row in rows}:
        raise SystemExit("Safe subset ID list mismatch")
    for row in rows:
        if (row.get("event_id") != records[row["id"]]["event_id"]
                or sha((row.get("text_full") or "").encode("utf-8"))
                != records[row["id"]]["text_sha256"]):
            raise SystemExit("Safe subset record hash or event mismatch")
    guide_bytes = guide_path.read_bytes()
    protocol = protocol_from_guide(guide_bytes.decode("utf-8"))
    out.mkdir(parents=True, exist_ok=False)
    (out / "run_manifest.json").write_text(json.dumps({
        "stage": "blind_A_B_C_not_arbitrated", "input_sha256": sha(input_bytes),
        "safe_manifest_sha256": sha(manifest_path.read_bytes()),
        "guide_sha256": sha(guide_bytes), "protocol_sha256": sha(protocol.encode("utf-8")),
        "system_prompt_sha256": sha(SYSTEM.encode("utf-8")),
        "roles": {role: {"provider": p, "model": MODELS[p][0]} for role, p in ROLES.items()},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    invalid_count = 0
    for role, provider in ROLES.items():
        with (out / f"annotator_{role}.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                party, facts = party_and_facts(row)
                user = json.dumps({"protocol": protocol, "id": row["id"],
                                   "event_id": row["event_id"],
                                   "subject_alias": row.get("subject_alias"),
                                   "text_party": party, "text_facts": facts,
                                   "fields": FIELD_TYPES}, ensure_ascii=False)
                item = {"id": row["id"], "event_id": row["event_id"],
                        "text_sha256": records[row["id"]]["text_sha256"],
                        "role": role, "provider": provider, "requested_model": MODELS[provider][0],
                        "request_sha256": sha((SYSTEM + "\n" + user).encode("utf-8")),
                        "annotated_at": datetime.now(timezone.utc).isoformat()}
                try:
                    response = call_json(provider, SYSTEM, user)
                    item.update({"fields": validate_fields(response["answer"], party, facts),
                                 "returned_model": response["returned_model"],
                                 "response_id": response["response_id"], "status": "valid_raw_annotation"})
                    if item["returned_model"] != MODELS[provider][0]:
                        raise ValueError("Returned model ID differs from approved model")
                except Exception as exc:
                    item.pop("fields", None)
                    item.update({"status": "invalid_raw_annotation", "error_type": type(exc).__name__})
                    invalid_count += 1
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
                print(json.dumps({"id": row["id"], "role": role, "status": item["status"]}))
    return 1 if invalid_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""C adjudicates every A/B/C disagreement after its blind labels are saved.

Usage: python run_flagship_arbitration.py <safe_manifest.json> <pilot50-safe.jsonl>
       <annotation-guideline.md> <blind_run_dir> <new_controlled_output_dir>
Each case is self-contained. Unanimous fields need no model call.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from flagship_client import MODELS, call_json, configured
from run_flagship_blind_annotation import (ROLES, party_and_facts, protocol_from_guide,
                                           validate_fields)
from validate_annotations import FIELD_TYPES

REASONS = {"model_reading", "evidence_missing", "guideline_ambiguity",
           "source_conflict", "schema_gap", "other"}
SYSTEM = (
    "你是第三模型 C 的逐字段仲裁员。你已在盲态独立标注，现查看匿名 A/B 及自己的 C 原标。"
    "只处理列出的分歧字段；优先采纳原标 A、B 或 C 的完整值与证据。"
    "只有三者均不足时才给 new，并附可在提供文本中逐字找到的证据。"
    "若指南、来源或 schema 不能决议，给 unresolved。只返回 JSON 对象："
    "{decisions:{字段:{adopt:A|B|C|new|unresolved,reason_code:代码,final:字段对象或 null}}}。"
    "不得把处罚结果或说理当事实，不得编造日期、金额上界或否定事实。"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def signature(item: dict) -> str:
    return json.dumps([item["status"], item["value"]], ensure_ascii=False, sort_keys=True)


def load_role(path: Path, expected: dict, provider: str) -> dict:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            rid = item["id"]
            if rid in rows:
                raise ValueError("Duplicate blind annotation ID")
            rows[rid] = item
    if set(rows) != set(expected):
        raise ValueError("Blind annotation coverage incomplete")
    for rid, item in rows.items():
        if (item.get("status") != "valid_raw_annotation"
                or item.get("provider") != provider
                or item.get("requested_model") != MODELS[provider][0]
                or item.get("returned_model") != MODELS[provider][0]
                or item.get("text_sha256") != expected[rid]["text_sha256"]
                or item.get("event_id") != expected[rid]["event_id"]
                or not item.get("response_id")):
            raise ValueError("Blind annotation invalid or model mismatch")
    return rows


def validate_decisions(answer: dict, disputed: dict, labels: dict,
                       party: str, facts: str) -> dict:
    if set(answer) != {"decisions"} or not isinstance(answer["decisions"], dict):
        raise ValueError("Arbitration response shape invalid")
    decisions = answer["decisions"]
    if set(decisions) != set(disputed):
        raise ValueError("Arbitration field coverage invalid")
    clean = {}
    for field, item in decisions.items():
        if not isinstance(item, dict) or item.get("adopt") not in {"A", "B", "C", "new", "unresolved"}:
            raise ValueError("Arbitration decision invalid")
        if item.get("reason_code") not in REASONS:
            raise ValueError("Arbitration reason code invalid")
        chosen = item["adopt"]
        if chosen in ROLES:
            final = labels[chosen][field]
        elif chosen == "new":
            final = item.get("final")
            # Reuse the strict whole-record validator for this one replacement.
            validate_fields({"fields": {**labels["A"], field: final}}, party, facts)
        else:
            final = None
        clean[field] = {"adopt": chosen, "reason_code": item["reason_code"], "final": final}
    return clean


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print(__doc__)
        return 2
    safe_manifest_path, input_path, guide_path, blind_dir, out = map(Path, argv[1:])
    if not configured("kimi"):
        raise SystemExit("OPENAI_API_KEY missing; C arbitration request not sent")
    repo = Path(__file__).resolve().parents[2]
    if out.resolve().is_relative_to(repo) or out.exists():
        raise SystemExit("Output must be a new controlled directory outside repository")
    safe = json.loads(safe_manifest_path.read_text(encoding="utf-8"))
    input_bytes = input_path.read_bytes()
    if sha(input_bytes) != safe.get("input_sha256") or safe.get("n_records") != 50:
        raise SystemExit("Frozen input mismatch")
    blind = json.loads((blind_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if (blind.get("input_sha256") != sha(input_bytes)
            or blind.get("safe_manifest_sha256") != sha(safe_manifest_path.read_bytes())
            or blind.get("guide_sha256") != sha(guide_path.read_bytes())
            or blind.get("roles") != {r: {"provider": p, "model": MODELS[p][0]}
                                      for r, p in ROLES.items()}):
        raise SystemExit("Blind run version or input mismatch")
    rows = [json.loads(line) for line in input_bytes.decode("utf-8").splitlines() if line.strip()]
    expected = {item["id"]: item for item in safe["records"]}
    annotations = {role: load_role(blind_dir / f"annotator_{role}.jsonl", expected, provider)
                   for role, provider in ROLES.items()}
    protocol = protocol_from_guide(guide_path.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=False)
    (out / "run_manifest.json").write_text(json.dumps({
        "stage": "C_field_arbitration", "input_sha256": sha(input_bytes),
        "safe_manifest_sha256": sha(safe_manifest_path.read_bytes()),
        "blind_manifest_sha256": sha((blind_dir / "run_manifest.json").read_bytes()),
        "guide_sha256": sha(guide_path.read_bytes()),
        "system_prompt_sha256": sha(SYSTEM.encode("utf-8")),
        "model": MODELS["kimi"][0],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    invalid_count = 0
    with (out / "decisions.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            rid = row["id"]
            party, facts = party_and_facts(row)
            labels = {role: annotations[role][rid]["fields"] for role in ROLES}
            disputed = {field: {role: labels[role][field] for role in ROLES}
                        for field in FIELD_TYPES
                        if len({signature(labels[role][field]) for role in ROLES}) > 1}
            item = {"id": rid, "event_id": row["event_id"],
                    "text_sha256": expected[rid]["text_sha256"], "disputed_fields": sorted(disputed),
                    "adjudicated_at": datetime.now(timezone.utc).isoformat()}
            if not disputed:
                item.update({"status": "valid_arbitration", "decisions": {}, "response_id": None})
            else:
                user = json.dumps({"protocol": protocol, "id": rid, "text_party": party,
                                   "text_facts": facts, "disputed": disputed}, ensure_ascii=False)
                item["request_sha256"] = sha((SYSTEM + "\n" + user).encode("utf-8"))
                try:
                    response = call_json("kimi", SYSTEM, user)
                    if response["returned_model"] != MODELS["kimi"][0]:
                        raise ValueError("Returned arbitration model mismatch")
                    item.update({"status": "valid_arbitration",
                                 "decisions": validate_decisions(response["answer"], disputed,
                                                                  labels, party, facts),
                                 "response_id": response["response_id"],
                                 "returned_model": response["returned_model"]})
                except Exception as exc:
                    item.update({"status": "invalid_arbitration", "error_type": type(exc).__name__})
                    invalid_count += 1
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            handle.flush()
            print(json.dumps({"id": rid, "disagreements": len(disputed), "status": item["status"]}))
    return 1 if invalid_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

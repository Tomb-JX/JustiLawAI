"""Deterministically merge A/B/C blind labels and C decisions; validate schema.

Usage: python assemble_flagship_candidate.py <safe_manifest.json> <pilot50-safe.jsonl>
       <annotation-guideline.md> <blind_run_dir> <arbitration_run_dir>
       <new_controlled_output_dir> [standards_approval.json]

Without a matching legal/schema standards approval, outputs remain a working set
and model_adjudicated_completed is zero.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[2] / "justilaw-api"
sys.path.insert(0, str(API))
from app.discretion.schema import AmountRange, GamblingElements, Intent, SCHEMA_VERSION  # noqa: E402

from flagship_client import MODELS
from run_flagship_arbitration import load_role, signature
from run_flagship_blind_annotation import ROLES, party_and_facts, validate_fields
from screen_standard_risks import OPEN_AMOUNT
from validate_annotations import FIELD_TYPES


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_decisions(path: Path, expected: dict) -> dict:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if item["id"] in rows:
                raise ValueError("Duplicate arbitration ID")
            rows[item["id"]] = item
    if set(rows) != set(expected):
        raise ValueError("Arbitration coverage incomplete")
    return rows


def evidence_offsets(quote: str, party: str, facts: str, facts_start: int) -> tuple[int, int]:
    starts = []
    for section, base in ((party, 0), (facts, facts_start)):
        pos = section.find(quote)
        while pos >= 0:
            starts.append(base + pos)
            pos = section.find(quote, pos + 1)
    if len(starts) != 1:
        raise ValueError("Evidence quote has no unique offset in model input")
    return starts[0], starts[0] + len(quote)


def nested_schema_record(row: dict, fields: dict) -> dict:
    party, facts = party_and_facts(row)
    facts_start = (row["segments"] or {})["text_facts"][0]
    nested = {"schema_version": SCHEMA_VERSION,
              "meta": {"behavior_date": row.get("behavior_date")}}
    for path, item in fields.items():
        group, name = path.split(".")
        evidence = []
        for quote in item["evidence"]:
            start, end = evidence_offsets(quote, party, facts, facts_start)
            evidence.append({"quote": quote, "start": start, "end": end})
        nested.setdefault(group, {})[name] = {
            "value": item["value"], "status": item["status"], "evidence": evidence}
    return GamblingElements.model_validate(nested).model_dump(mode="json")


def standards_ok(path: Path | None, guide_hash: str, rows: list[dict] | tuple = ()) -> bool:
    if path is None:
        return False
    doc = json.loads(path.read_text(encoding="utf-8"))
    schema_hash = sha((API / "app" / "discretion" / "schema.py").read_bytes())
    description = Intent.model_fields["profit_purpose"].description or ""
    schema_parts = tuple(int(part) for part in SCHEMA_VERSION.split(".")[:2])
    guide_adoption_implemented = (schema_parts >= (1, 1) and schema_parts[0] == 1
                                  and "只收台费场地费" in description
                                  and "对其他参赌人的营利事实不算本人的" in description)
    try:
        AmountRange.model_validate({"min": 1, "max": None})
        open_bound_implemented = True
    except Exception:
        open_bound_implemented = False
    return (doc.get("guide_sha256") == guide_hash
            and doc.get("schema_source_sha256") == schema_hash
            and doc.get("schema_version") == SCHEMA_VERSION
            and doc.get("profit_purpose_decision") == "engine_schema_1.1.0"
            and guide_adoption_implemented
            and doc.get("open_amount_decision") == "schema_supports_open_bound"
            and open_bound_implemented
            and doc.get("decision_source") == "engine_collab_log_2026-10-17"
            and doc.get("adopted_by") == "engine"
            and bool(doc.get("adopted_at")))


def main(argv: list[str]) -> int:
    if len(argv) not in (7, 8):
        print(__doc__)
        return 2
    safe_path, input_path, guide_path, blind_dir, arbitration_dir, out = map(Path, argv[1:7])
    approval_path = Path(argv[7]) if len(argv) == 8 else None
    repo = Path(__file__).resolve().parents[2]
    if out.resolve().is_relative_to(repo) or out.exists():
        raise SystemExit("Output must be a new controlled directory outside repository")
    safe = json.loads(safe_path.read_text(encoding="utf-8"))
    input_bytes = input_path.read_bytes()
    guide_hash = sha(guide_path.read_bytes())
    if sha(input_bytes) != safe.get("input_sha256") or safe.get("n_records") != 50:
        raise SystemExit("Frozen input mismatch")
    blind_manifest_path = blind_dir / "run_manifest.json"
    arb_manifest_path = arbitration_dir / "run_manifest.json"
    blind_manifest = json.loads(blind_manifest_path.read_text(encoding="utf-8"))
    arb_manifest = json.loads(arb_manifest_path.read_text(encoding="utf-8"))
    if (blind_manifest.get("input_sha256") != sha(input_bytes)
            or blind_manifest.get("guide_sha256") != guide_hash
            or arb_manifest.get("input_sha256") != sha(input_bytes)
            or arb_manifest.get("guide_sha256") != guide_hash
            or arb_manifest.get("blind_manifest_sha256") != sha(blind_manifest_path.read_bytes())
            or arb_manifest.get("model") != MODELS["kimi"][0]):
        raise SystemExit("Blind and arbitration run manifests do not match")
    rows = [json.loads(line) for line in input_bytes.decode("utf-8").splitlines() if line.strip()]
    expected = {item["id"]: item for item in safe["records"]}
    if len(rows) != 50 or set(expected) != {row["id"] for row in rows}:
        raise SystemExit("Frozen input record coverage mismatch")
    annotations = {role: load_role(blind_dir / f"annotator_{role}.jsonl", expected, provider)
                   for role, provider in ROLES.items()}
    decisions = load_decisions(arbitration_dir / "decisions.jsonl", expected)
    valid = []
    errors = []
    for row in rows:
        rid = row["id"]
        try:
            if (sha((row.get("text_full") or "").encode("utf-8")) != expected[rid]["text_sha256"]
                    or row["event_id"] != expected[rid]["event_id"]):
                raise ValueError("Input record hash or event changed")
            labels = {role: annotations[role][rid]["fields"] for role in ROLES}
            disputed = {field for field in FIELD_TYPES
                        if len({signature(labels[role][field]) for role in ROLES}) > 1}
            decision = decisions[rid]
            if (decision.get("status") != "valid_arbitration"
                    or decision.get("text_sha256") != expected[rid]["text_sha256"]
                    or decision.get("event_id") != expected[rid]["event_id"]
                    or set(decision.get("decisions", {})) != disputed):
                raise ValueError("Arbitration missing or mismatched")
            final = dict(labels["A"])
            for field in disputed:
                choice = decision["decisions"][field]
                if choice.get("adopt") == "unresolved":
                    raise ValueError("Field remains unresolved")
                if choice.get("adopt") in ROLES:
                    source = labels[choice["adopt"]][field]
                    if choice.get("final") != source:
                        raise ValueError("Adopted model field was not copied exactly")
                    final[field] = source
                elif choice.get("adopt") == "new":
                    final[field] = choice["final"]
                else:
                    raise ValueError("Invalid arbitration choice")
            party, facts = party_and_facts(row)
            validate_fields({"fields": final}, party, facts)
            nested = nested_schema_record(row, final)
            valid.append({"id": rid, "event_id": row["event_id"],
                          "text_sha256": expected[rid]["text_sha256"],
                          "fields": final, "gambling_elements": nested,
                          "label_origin": "model-adjudicated", "human_review": False})
        except Exception as exc:
            errors.append({"id": rid, "category": type(exc).__name__})
    approved = standards_ok(approval_path, guide_hash, rows)
    completed = 50 if approved and not errors and len(valid) == 50 else 0
    out.mkdir(parents=True, exist_ok=False)
    with (out / "arbitrated_working.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for item in valid:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    (out / "validation.json").write_text(json.dumps({
        "n_valid": len(valid), "n_errors": len(errors), "errors": errors,
        "standards_approval_valid": approved, "model_adjudicated_completed": completed,
        "n_open_amount_phrase_candidates": sum(bool(OPEN_AMOUNT.search(row.get("text_facts") or ""))
                                              for row in rows),
        "human_verified_completed": 0,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "input_sha256": sha(input_bytes), "guide_sha256": guide_hash,
        "blind_manifest_sha256": sha(blind_manifest_path.read_bytes()),
        "arbitration_manifest_sha256": sha(arb_manifest_path.read_bytes()),
        "working_file_sha256": sha((out / "arbitrated_working.jsonl").read_bytes()),
        "label_origin": "model-adjudicated", "human_review": False,
        "model_adjudicated_completed": completed, "human_verified_completed": 0,
        "status": "candidate_complete" if completed else "working_pending_validation_or_standards",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n_valid": len(valid), "n_errors": len(errors),
                      "standards_approval_valid": approved,
                      "model_adjudicated_completed": completed}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

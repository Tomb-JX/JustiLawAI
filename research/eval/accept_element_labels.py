"""I-20 要素教师试点验收：结构、证据、数值与双模型分歧。

输入每行：{id, input:{target,facts_text,meta_text,text_full,text_orig_sha256}, elements:{七组},
             label_provenance:"model-adjudicated", human_review:false}。
只输出聚合与 ID/字段问题清单，不写原文或引文。没有人工真值时不报告字段准确率。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "justilaw-api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.discretion.element_labels import FIELD_INFO, PROMPT_VERSION, validate_teacher_output  # noqa: E402
from app.discretion.extract import parse_amount  # noqa: E402
from app.discretion.schema import AmountRange, KEY_FIELDS, SCHEMA_VERSION  # noqa: E402
from agreement import agreement, normalize  # noqa: E402
from key_field_presence import MARKERS  # noqa: E402

CHECKER_VERSION = "element-accept-v1"
_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*(?:万)?元(?:以上|余|多|以下)?")
_NUMBER = re.compile(r"(?<!\d)\d+(?:\.\d+)?(?!\d)")


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _flatten(rec: object) -> dict:
    if not isinstance(rec, dict):
        return {}
    out = {}
    for path in FIELD_INFO:
        group, name = path.split(".")
        fields = rec.get(group)
        if isinstance(fields, dict) and name in fields:
            out[path] = fields[name]
    return out


def _numeric_check(path: str, item: dict) -> bool | None:
    """只对原文中唯一的阿拉伯数额做机械对账；无法确定的留给仲裁。"""
    if item.get("status") != "明确" or item.get("value") is None:
        return None
    typ = FIELD_INFO[path][1]
    if typ not in (AmountRange, int, float):
        return None
    quote = " ".join(e.get("quote", "") for e in item.get("evidence", []) if isinstance(e, dict))
    if typ is AmountRange:
        mentions = _AMOUNT.findall(quote)
        if len(mentions) != 1:
            return None
        parsed = parse_amount(mentions[0])
        if parsed is None:
            return None
        return normalize(path, item["value"]) == normalize(path, parsed.model_dump())
    nums = _NUMBER.findall(quote)
    if len(nums) != 1:
        return None
    return float(item["value"]) == float(nums[0])


def evaluate(rows: list[dict], a_rows: list[dict] | None = None,
             b_rows: list[dict] | None = None) -> dict:
    issues: list[dict] = []
    ids = [str(r.get("id", "")) for r in rows]
    duplicate_ids = {rid for rid, count in Counter(ids).items() if count > 1}
    if duplicate_ids:
        issues.append({"id": "*", "field": "id", "code": "duplicate_id"})
    structural_bad: set[int] = set()
    evidence_total = evidence_hit = 0
    numeric_checked = numeric_hit = 0
    statuses = {p: Counter() for p in FIELD_INFO}
    marker_hits = Counter()
    for index, row in enumerate(rows):
        rid = str(row.get("id", ""))
        inp = row.get("input") or {}
        facts, meta = inp.get("facts_text") or "", inp.get("meta_text") or ""
        source = inp.get("text_full")
        if not isinstance(source, str):
            source = ""
        if not rid or not inp.get("target") or not re.fullmatch(r"[0-9a-f]{64}",
                                                       str(inp.get("text_orig_sha256", ""))) or not source:
            issues.append({"id": rid, "field": "input", "code": "bad_input_envelope"})
            structural_bad.add(index)
        elif hashlib.sha256(source.encode("utf-8")).hexdigest() != inp["text_orig_sha256"]:
            issues.append({"id": rid, "field": "input", "code": "text_hash_mismatch"})
            structural_bad.add(index)
        if rid in duplicate_ids:
            structural_bad.add(index)
        if row.get("label_provenance") != "model-adjudicated" or row.get("human_review") is not False:
            issues.append({"id": rid, "field": "provenance", "code": "bad_provenance"})
            structural_bad.add(index)
        if row.get("element_schema_version") != SCHEMA_VERSION or row.get("element_prompt_version") != PROMPT_VERSION:
            issues.append({"id": rid, "field": "version", "code": "bad_version"})
            structural_bad.add(index)
        found = validate_teacher_output(row.get("elements"), evidence_text=source, located=True)
        for issue in found:
            issues.append({"id": rid, "field": issue.field, "code": issue.code})
            if issue.code not in {"evidence_not_found", "evidence_offset_mismatch"}:
                structural_bad.add(index)
        fields = _flatten(row.get("elements"))
        for path in FIELD_INFO:
            item = fields.get(path)
            if not isinstance(item, dict):
                continue
            statuses[path][str(item.get("status", "invalid"))] += 1
            for ev in item.get("evidence", []) if isinstance(item.get("evidence"), list) else []:
                if isinstance(ev, dict) and isinstance(ev.get("quote"), str) and ev["quote"].strip():
                    evidence_total += 1
                    start, end = ev.get("start"), ev.get("end")
                    evidence_hit += (type(start) is int and type(end) is int
                                     and source[start:end] == ev["quote"])
            if item.get("status") == "明确" and path in FIELD_INFO:
                try:
                    checked = _numeric_check(path, item)
                except (TypeError, ValueError, KeyError):
                    checked = None
                if checked is not None:
                    numeric_checked += 1
                    numeric_hit += checked
                    if not checked:
                        issues.append({"id": rid, "field": path, "code": "numeric_mismatch"})
        for path in KEY_FIELDS:
            if re.search(MARKERS[path], source):
                marker_hits[path] += 1

    n = len(rows)
    absent_by_field = {p: round(statuses[p]["未提及"] / n, 4) if n else None for p in FIELD_INFO}
    presence_warnings = []
    for path in KEY_FIELDS:
        if n:
            marker_presence = marker_hits[path] / n
            label_presence = 1 - statuses[path]["未提及"] / n
            if abs(marker_presence - label_presence) > 0.20:
                presence_warnings.append({"field": path, "marker_presence": round(marker_presence, 4),
                                          "label_presence": round(label_presence, 4)})
    evidence_rate = evidence_hit / evidence_total if evidence_total else None
    numeric_rate = numeric_hit / numeric_checked if numeric_checked else None
    arbitration = None
    if a_rows is not None and b_rows is not None:
        a = {str(r["id"]): _flatten(r.get("elements")) for r in a_rows}
        b = {str(r["id"]): _flatten(r.get("elements")) for r in b_rows}
        rep = agreement(a, b)
        union = sum(f["n_union"] for f in rep["fields"])
        disagreements = sum(len(f["disagreements"]) for f in rep["fields"])
        arbitration = {"common_records": rep["records_common"], "union_pairs": union,
                       "disagree_pairs": disagreements,
                       "disagreement_rate": disagreements / union if union else None,
                       "key_numeric_pairs": rep["gate"]["key_numeric_pairs"],
                       "key_numeric_exact_rate": rep["gate"]["key_numeric_exact_rate"],
                       "source": "research/eval/agreement.py union 口径"}
    prompt_revision_needed = (arbitration is not None and arbitration["disagreement_rate"] is not None
                              and arbitration["disagreement_rate"] > 0.20)
    report = {
        "checker": CHECKER_VERSION, "records": n, "expected_pilot_range": [200, 300],
        "model_adjudicated_not_human_gold": True,
        "schema_valid_records": n - len(structural_bad),
        "schema_valid_rate": (n - len(structural_bad)) / n if n else None,
        "evidence_quotes": evidence_total, "evidence_hit_rate": evidence_rate,
        "numeric_checkable": numeric_checked, "numeric_consistency_rate": numeric_rate,
        "absent_rate_by_field": absent_by_field,
        "presence_proxy_warnings_gt_20pp": presence_warnings,
        "arbitration": arbitration, "prompt_revision_needed": prompt_revision_needed,
        "issue_counts": dict(Counter(i["code"] for i in issues)), "issues": issues,
    }
    report["pilot_pass"] = (200 <= n <= 300 and report["schema_valid_rate"] == 1.0
                            and evidence_rate is not None and evidence_rate >= .95
                            and arbitration is not None and arbitration["common_records"] == n
                            and not prompt_revision_needed)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", type=Path)
    ap.add_argument("--a", type=Path, help="双盲模型 A JSONL（可选）")
    ap.add_argument("--b", type=Path, help="双盲模型 B JSONL（可选）")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if bool(args.a) != bool(args.b):
        ap.error("--a 与 --b 必须一起提供")
    rep = evaluate(_rows(args.labels), _rows(args.a) if args.a else None,
                   _rows(args.b) if args.b else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), "utf-8")
    print(f"{rep['records']} 件；结构 {rep['schema_valid_rate']:.1%}；"
          f"证据 {rep['evidence_hit_rate']:.1%}" if rep["evidence_hit_rate"] is not None
          else f"{rep['records']} 件；无可验引文", "；试点通过" if rep["pilot_pass"] else "；待修复")
    return 0 if rep["pilot_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

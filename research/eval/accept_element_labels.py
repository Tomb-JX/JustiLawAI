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

CHECKER_VERSION = "element-accept-v2"
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


def _classify_divergence(a_item: dict, b_item: dict) -> str:
    """Classify A/B disagreement on one field into divergence type.

    Returns: 'status_only' (same value, different status),
             'value' (different values),
             'evidence_only' (same value+status, different evidence quotes),
             'absent_vs_present' (one absent, one present).
    """
    a_val, b_val = a_item.get("value"), b_item.get("value")
    a_status, b_status = a_item.get("status"), b_item.get("status")
    a_absent = a_status == "未提及" or a_val is None
    b_absent = b_status == "未提及" or b_val is None
    if a_absent != b_absent:
        return "absent_vs_present"
    if a_absent and b_absent:
        return "evidence_only"
    if a_val != b_val:
        return "value"
    if a_status != b_status:
        return "status_only"
    return "evidence_only"


def classify_divergences(a_rows: dict[str, dict], b_rows: dict[str, dict]) -> dict:
    """Classify all A/B divergences by type per field.

    Returns {field: {divergence_type: count, ...}, ...} plus per-field lists of IDs.
    """
    ids = sorted(set(a_rows) & set(b_rows))
    result: dict[str, dict] = {}
    for rid in ids:
        a_fields, b_fields = a_rows[rid], b_rows[rid]
        for path in FIELD_INFO:
            a_item = a_fields.get(path, {})
            b_item = b_fields.get(path, {})
            a_val, b_val = a_item.get("value"), b_item.get("value")
            a_status = a_item.get("status", "未提及")
            b_status = b_item.get("status", "未提及")
            a_absent = a_status == "未提及" or a_val is None
            b_absent = b_status == "未提及" or b_val is None
            if a_absent and b_absent:
                continue
            if a_status == b_status and a_val == b_val:
                continue
            div_type = _classify_divergence(a_item, b_item)
            entry = result.setdefault(path, {"status_only": 0, "value": 0,
                                              "evidence_only": 0, "absent_vs_present": 0,
                                              "status_only_ids": [], "value_ids": [],
                                              "evidence_only_ids": [], "absent_vs_present_ids": []})
            entry[div_type] += 1
            entry[f"{div_type}_ids"].append(rid)
    return result


def compare_predictions(pred_rows: dict[str, dict], ref_rows: dict[str, dict]) -> dict:
    """Compare M1 extraction predictions against teacher reference labels.

    Returns per-field precision/recall for categorical fields and
    MAE/accuracy for numeric fields, plus a summary.
    """
    from collections import defaultdict
    ids = sorted(set(pred_rows) & set(ref_rows))
    if not ids:
        return {"records_common": 0, "fields": {}, "summary": {}}

    field_stats: dict[str, dict] = {}
    for path in FIELD_INFO:
        correct = total = 0
        pred_present = ref_present = both_present = 0
        values_match = statuses_match = 0
        for rid in ids:
            pred = pred_rows[rid].get(path, {})
            ref = ref_rows[rid].get(path, {})
            p_status = pred.get("status", "未提及")
            r_status = ref.get("status", "未提及")
            p_absent = p_status == "未提及" or pred.get("value") is None
            r_absent = r_status == "未提及" or ref.get("value") is None
            if r_absent:
                ref_present += 0
            else:
                ref_present += 1
            if not p_absent:
                pred_present += 1
            if not p_absent and not r_absent:
                both_present += 1
                total += 1
                if pred.get("value") == ref.get("value"):
                    values_match += 1
                    correct += 1
                if p_status == r_status:
                    statuses_match += 1
            elif p_absent != r_absent:
                total += 1

        precision = values_match / pred_present if pred_present else None
        recall = values_match / ref_present if ref_present else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
        field_stats[path] = {
            "pred_present": pred_present, "ref_present": ref_present,
            "both_present": both_present, "values_match": values_match,
            "statuses_match": statuses_match, "total": total,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
        }

    # Summary over KEY_FIELDS
    key_stats = {p: s for p, s in field_stats.items() if p in KEY_FIELDS}
    key_prec = [s["precision"] for s in key_stats.values() if s["precision"] is not None]
    key_rec = [s["recall"] for s in key_stats.values() if s["recall"] is not None]
    summary = {
        "records_common": len(ids),
        "key_fields_mean_precision": round(sum(key_prec) / len(key_prec), 4) if key_prec else None,
        "key_fields_mean_recall": round(sum(key_rec) / len(key_rec), 4) if key_rec else None,
    }
    return {"records_common": len(ids), "fields": field_stats, "summary": summary}


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
    divergence_by_field = None
    if a_rows is not None and b_rows is not None:
        a = {str(r["id"]): _flatten(r.get("elements")) for r in a_rows}
        b = {str(r["id"]): _flatten(r.get("elements")) for r in b_rows}
        rep = agreement(a, b)
        union = sum(f["n_union"] for f in rep["fields"])
        disagreements = sum(len(f["disagreements"]) for f in rep["fields"])
        # E-06: classify divergences by type
        div_raw = classify_divergences(a, b)
        div_summary = {}
        for path, counts in div_raw.items():
            div_summary[path] = {k: v for k, v in counts.items() if not k.endswith("_ids")}
        divergence_by_field = div_summary
        # Aggregate divergence type counts
        type_totals = {"status_only": 0, "value": 0, "evidence_only": 0, "absent_vs_present": 0}
        for counts in div_raw.values():
            for t in type_totals:
                type_totals[t] += counts.get(t, 0)
        arbitration = {"common_records": rep["records_common"], "union_pairs": union,
                       "disagree_pairs": disagreements,
                       "disagreement_rate": disagreements / union if union else None,
                       "divergence_types": type_totals,
                       "divergence_by_field": div_summary,
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
    # E-06: batch criteria for ≤12 smoke and ≤36 spec
    structural_ok = report["schema_valid_rate"] == 1.0
    evidence_ok = evidence_rate is not None and evidence_rate >= .95
    numeric_ok = (report["numeric_consistency_rate"] is None
                  or report["numeric_consistency_rate"] >= .90)
    report["smoke_pass"] = (1 <= n <= 12 and structural_ok and evidence_ok and numeric_ok)
    report["spec_pass"] = (13 <= n <= 36 and structural_ok and evidence_ok
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

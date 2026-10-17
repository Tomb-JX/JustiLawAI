"""试标标注产物校验（金标质检线）：校验标注员输出的 JSONL 是否符合协议。

检查：id 覆盖率（对照 pilot50）、36 字段齐全、status 枚举合法、未提及则值为空、
有值必有证据、value 类型与字段类型匹配、证据 quote 能在 text_full 中逐字命中。

用法：python validate_annotations.py <标注目录或.jsonl> <pilot50.jsonl> <outdir> <标注员名>
输出：outdir/validation_<标注员名>.json；有 error 时退出码 1。
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

FIELD_TYPES: dict[str, str] = {
    "conduct.behavior_type": "enum", "conduct.role": "enum", "conduct.method": "enum",
    "conduct.times": "int", "conduct.duration_days": "float", "conduct.cheating": "bool",
    "amounts.personal_stake": "amount", "amounts.per_bet": "amount", "amounts.onsite_stake_total": "amount",
    "amounts.cumulative_stake": "amount", "amounts.commission": "amount", "amounts.illegal_gain": "amount",
    "persons.participant_count": "int", "persons.cumulative_participants": "int",
    "persons.minors_involved": "bool", "persons.civil_servant": "bool", "persons.relatives_only": "bool",
    "persons.abroad_organized_count": "int",
    "venue.venue_type": "enum", "intent.profit_purpose": "bool",
    "circumstances.last_prior_penalty_date": "date",
    "circumstances.surrendered": "bool", "circumstances.truthful_statement": "bool",
    "circumstances.admits_and_accepts": "bool", "circumstances.remedied_consequence": "bool",
    "circumstances.victim_forgiveness": "bool", "circumstances.coerced_or_lured": "bool",
    "circumstances.meritorious": "bool", "circumstances.instigated_others": "bool",
    "circumstances.retaliation": "bool", "circumstances.obstructed_police": "bool",
    "circumstances.minor_circumstance": "enum", "circumstances.first_offense": "bool",
    "circumstances.violations_last_year": "int",
    "person.age": "int", "person.pregnant_or_nursing": "bool",
}
STATUSES = {"明确", "推断", "未提及"}
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")


def norm_text(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    ann_path, pilot_path, outdir, who = Path(argv[1]), Path(argv[2]), Path(argv[3]), argv[4]

    files = sorted(ann_path.glob("*.jsonl")) if ann_path.is_dir() else [ann_path]
    errors: list[dict] = []
    warns: list[dict] = []
    anns: dict[str, dict] = {}
    for fp in files:
        for number, line in enumerate(fp.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                try:
                    rec = json.loads(line)
                    rid = rec["id"]
                    if not isinstance(rid, str) or not SAFE_ID.fullmatch(rid):
                        raise ValueError
                    if rid in anns:
                        errors.append({"id": rid, "field": "-", "problem": "重复 ID"})
                    else:
                        anns[rid] = rec
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    errors.append({"id": "-", "field": "-", "problem": f"非法 JSON 或 ID：{fp.name}:{number}"})
    pilot_files = sorted(pilot_path.glob("*.jsonl")) if pilot_path.is_dir() else [pilot_path]
    pilot: dict[str, dict] = {}
    for fp in pilot_files:
        for number, line in enumerate(fp.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                try:
                    record = json.loads(line)
                    rid = record["id"]
                    if not isinstance(rid, str) or not SAFE_ID.fullmatch(rid):
                        raise ValueError
                    if rid in pilot:
                        errors.append({"id": rid, "field": "-", "problem": "输入重复 ID"})
                    pilot[rid] = record
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    errors.append({"id": "-", "field": "-", "problem": f"输入非法 JSON 或 ID：{fp.name}:{number}"})
    ev_total = ev_hit = 0
    for rid, rec in anns.items():
        fields = rec.get("fields")
        if not isinstance(fields, dict):
            errors.append({"id": rid, "field": "-", "problem": "fields 缺失或不是对象"})
            continue
        missing = [f for f in FIELD_TYPES if f not in fields]
        extra = [f for f in fields if f not in FIELD_TYPES]
        if missing:
            errors.append({"id": rid, "field": "-", "problem": f"缺字段 {len(missing)}: {missing[:6]}…"})
        if extra:
            errors.append({"id": rid, "field": "-", "problem": f"多余字段 {len(extra)} 个"})
        text = norm_text(pilot.get(rid, {}).get("text_full", ""))
        for field, judg in fields.items():
            ftype = FIELD_TYPES.get(field)
            if ftype is None:
                continue
            if not isinstance(judg, dict):
                errors.append({"id": rid, "field": field, "problem": "字段值不是对象"})
                continue
            status = judg.get("status")
            if status not in STATUSES:
                errors.append({"id": rid, "field": field, "problem": "status 非法"})
                continue
            value = judg.get("value")
            quotes = judg.get("evidence") or []
            if not isinstance(quotes, list):
                errors.append({"id": rid, "field": field, "problem": "证据应为列表"})
                quotes = []
            if status == "未提及":
                if value is not None:
                    errors.append({"id": rid, "field": field, "problem": "未提及但值非空"})
                continue
            if value is None:
                errors.append({"id": rid, "field": field, "problem": "有状态但值为空"})
            if not quotes:
                errors.append({"id": rid, "field": field, "problem": "有值但无证据"})
            for q in quotes:
                ev_total += 1
                if isinstance(q, str) and norm_text(q) and norm_text(q) in text:
                    ev_hit += 1
                else:
                    errors.append({"id": rid, "field": field, "problem": "证据不在冻结正文"})
            try:
                if ftype == "amount":
                    if not (isinstance(value, dict) and "min" in value and "max" in value
                            and math.isfinite(float(value["min"])) and 0 <= float(value["min"])
                            and (value["max"] is None or
                                 (math.isfinite(float(value["max"]))
                                  and float(value["min"]) <= float(value["max"])))):
                        errors.append({"id": rid, "field": field, "problem": "金额类型或区间非法"})
                elif ftype == "int":
                    if not isinstance(value, int) or isinstance(value, bool):
                        errors.append({"id": rid, "field": field, "problem": "应为整数"})
                elif ftype == "float":
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                        errors.append({"id": rid, "field": field, "problem": "应为有限数值"})
                elif ftype == "bool":
                    if not isinstance(value, bool):
                        errors.append({"id": rid, "field": field, "problem": "应为布尔"})
                elif ftype == "date":
                    if not (isinstance(value, str) and DATE_RE.match(value)):
                        errors.append({"id": rid, "field": field, "problem": "应为 YYYY-MM-DD"})
            except (TypeError, ValueError):
                errors.append({"id": rid, "field": field, "problem": "类型检查失败"})

    missing_ids = sorted(set(pilot) - set(anns))
    if missing_ids:
        errors.append({"id": "-", "field": "-", "problem": f"缺记录 {len(missing_ids)}: {missing_ids}"})
    extra_ids = sorted(set(anns) - set(pilot))
    if extra_ids:
        errors.append({"id": "-", "field": "-", "problem": f"多余记录 {len(extra_ids)}: {extra_ids}"})

    report = {
        "annotator": who, "files": [str(f) for f in files], "n_records": len(anns),
        "n_errors": len(errors), "n_warnings": len(warns),
        "evidence": {"total": ev_total, "verbatim_hits": ev_hit,
                     "hit_rate": (ev_hit / ev_total) if ev_total else None},
        "errors": errors[:200], "warnings": warns,
    }
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"validation_{who}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"annotator": who, "n_records": len(anns), "n_errors": len(errors),
                      "evidence_hit_rate": report["evidence"]["hit_rate"]}, ensure_ascii=False))
    if errors:
        print(f"validation -> {out}（{len(errors)} 个 error）", file=sys.stderr)
        return 1
    print(f"validation -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

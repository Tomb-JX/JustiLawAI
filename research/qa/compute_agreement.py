"""试标一致性计算（金标质检线）：双标注员 JSONL → 分类字段 Cohen's κ、数值完全一致率、
证据命中检查与分歧清单。对应门禁 G0.3：关键分类字段 κ ≥ 0.80，关键数值字段完全一致率 ≥ 95%。

口径：
  - 每字段分别统计，未提及（value 为空或 status=未提及）视为一个独立类别。
  - kappa_all：全部试标记录上的 κ（未提及也作为类别参与）——参考口径。
  - kappa_union：至少一方有值的记录上的 κ——门禁主口径。
  - kappa_valued：只在双方都有值（含推断）的记录上的 κ——观察"值能否对上"。
  - 数值字段（amounts 的 {min,max}、整数、日期）门禁完全一致率在至少一方有值的记录上计算；
    双方有值一致率仅作诊断参考。
  - 关键字段集 K 按门禁 §3.1（行为类型、角色、方式、个人赌资、现场赌资、抽头、参赌人数、
    营利目的、一年内处罚次数、年龄）。
  - 证据命中：非"未提及"字段的每段证据 quote 必须能在 text_full 中逐字找到（空白规范化后）。

用法：
  python compute_agreement.py <annotatorA.jsonl或目录> <annotatorB.jsonl或目录> <试标输入.jsonl或分片目录> <outdir>

输出：outdir/agreement_report.json、agreement_report.md、disagreements.csv
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

FIELD_TYPES: dict[str, str] = {}
for _f in ("times",):
    FIELD_TYPES[f"conduct.{_f}"] = "int"
FIELD_TYPES["conduct.duration_days"] = "float"
for _f in ("cheating",):
    FIELD_TYPES[f"conduct.{_f}"] = "bool"
for _f in ("personal_stake", "per_bet", "onsite_stake_total", "cumulative_stake", "commission", "illegal_gain"):
    FIELD_TYPES[f"amounts.{_f}"] = "amount"
FIELD_TYPES["persons.participant_count"] = "int"
FIELD_TYPES["persons.cumulative_participants"] = "int"
for _f in ("minors_involved", "civil_servant", "relatives_only"):
    FIELD_TYPES[f"persons.{_f}"] = "bool"
FIELD_TYPES["persons.abroad_organized_count"] = "int"
FIELD_TYPES["venue.venue_type"] = "enum"
FIELD_TYPES["intent.profit_purpose"] = "bool"
FIELD_TYPES["circumstances.last_prior_penalty_date"] = "date"
for _f in ("surrendered", "truthful_statement", "admits_and_accepts", "remedied_consequence",
           "victim_forgiveness", "coerced_or_lured", "meritorious", "instigated_others",
           "retaliation", "obstructed_police"):
    FIELD_TYPES[f"circumstances.{_f}"] = "bool"
FIELD_TYPES["circumstances.minor_circumstance"] = "enum"
FIELD_TYPES["circumstances.first_offense"] = "bool"
FIELD_TYPES["circumstances.violations_last_year"] = "int"
FIELD_TYPES["person.age"] = "int"
FIELD_TYPES["person.pregnant_or_nursing"] = "bool"
for _f in ("behavior_type", "role", "method"):
    FIELD_TYPES[f"conduct.{_f}"] = "enum"

CATEGORICAL = {p for p, t in FIELD_TYPES.items() if t in ("enum", "bool")}
NUMERIC = {p for p, t in FIELD_TYPES.items() if t in ("int", "float", "amount", "date")}

KEY_CATEGORICAL = ["conduct.behavior_type", "conduct.role", "conduct.method", "intent.profit_purpose"]
KEY_NUMERIC = ["amounts.personal_stake", "amounts.onsite_stake_total", "amounts.commission",
               "persons.participant_count", "circumstances.last_prior_penalty_date", "person.age"]

ALL_FIELDS = list(FIELD_TYPES)


def norm_text(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def is_empty(judg: dict | None) -> bool:
    if not judg:
        return True
    if (judg.get("status") or "未提及") == "未提及":
        return True
    return judg.get("value") is None


def equal_values(a, b, ftype: str) -> bool:
    if ftype == "amount":
        try:
            same_min = abs(float(a["min"]) - float(b["min"])) < 1e-9
            max_a, max_b = a["max"], b["max"]
            same_max = (max_a is None and max_b is None) or (
                max_a is not None and max_b is not None
                and abs(float(max_a) - float(max_b)) < 1e-9)
            return same_min and same_max
        except (TypeError, KeyError, ValueError):
            return False
    if ftype in ("float",):
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return False
    return a == b


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's κ on (a, b) category pairs; None when undefined (n<2 or single category)."""
    n = len(pairs)
    if n < 2:
        return None
    obs = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    exp = sum(ca.get(k, 0) * cb.get(k, 0) for k in set(ca) | set(cb)) / (n * n)
    if exp >= 1.0:
        return None
    return (obs - exp) / (1 - exp)


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    path_a, path_b, path_pilot, outdir = (Path(argv[1]), Path(argv[2]), Path(argv[3]), Path(argv[4]))

    def load(p: Path) -> dict[str, dict]:
        """p 可以是一个 .jsonl 文件，也可以是目录（读取其中全部 *.jsonl，按文件名排序拼接）。"""
        files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
        out = {}
        for fp in files:
            for line in fp.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    if rec["id"] in out:
                        raise SystemExit(f"重复 id {rec['id']} 于 {fp}")
                    out[rec["id"]] = rec
        return out

    ann_a, ann_b = load(path_a), load(path_b)
    pilot = load(path_pilot)
    ids = sorted(set(ann_a) & set(ann_b), key=lambda i: list(pilot).index(i) if i in pilot else 999)
    missing = (set(pilot) - set(ann_a)) | (set(pilot) - set(ann_b))
    extra = (set(ann_a) | set(ann_b)) - set(pilot)

    per_field: dict[str, dict] = {}
    disagreements: list[dict] = []
    evidence_total = evidence_hit = 0

    for field in ALL_FIELDS:
        ftype = FIELD_TYPES[field]
        pairs_all: list[tuple[str, str]] = []
        pairs_valued: list[tuple[str, str]] = []
        pairs_union: list[tuple[str, str]] = []
        both_equal_valued = 0
        for rid in ids:
            ja = (ann_a[rid].get("fields") or {}).get(field)
            jb = (ann_b[rid].get("fields") or {}).get(field)
            ea, eb = is_empty(ja), is_empty(jb)
            va = None if ea else ja["value"]
            vb = None if eb else jb["value"]
            cat_a = "未提及" if ea else json.dumps(va, ensure_ascii=False, sort_keys=True)
            cat_b = "未提及" if eb else json.dumps(vb, ensure_ascii=False, sort_keys=True)
            pairs_all.append((cat_a, cat_b))
            if not (ea and eb):
                pairs_union.append((cat_a, cat_b))
            if not ea and not eb:
                pairs_valued.append((cat_a, cat_b))
                if equal_values(va, vb, ftype):
                    both_equal_valued += 1
                elif cat_a != cat_b:
                    disagreements.append({
                        "id": rid, "field": field, "type": ftype,
                        "a_status": ja.get("status"), "a_value": json.dumps(va, ensure_ascii=False),
                        "b_status": jb.get("status"), "b_value": json.dumps(vb, ensure_ascii=False),
                    })
            elif cat_a != cat_b:
                disagreements.append({
                    "id": rid, "field": field, "type": ftype,
                    "a_status": (ja or {}).get("status", "未提及"), "a_value": "-" if ea else json.dumps(va, ensure_ascii=False),
                    "b_status": (jb or {}).get("status", "未提及"), "b_value": "-" if eb else json.dumps(vb, ensure_ascii=False),
                })
        n_both = len(pairs_valued)
        per_field[field] = {
            "type": ftype,
            "key": field in KEY_CATEGORICAL or field in KEY_NUMERIC,
            "n_records": len(ids),
            "n_both_valued": n_both,
            "n_union_valued": len(pairs_union),
            "presence_agreement": (len(ids) - sum(1 for rid in ids
                if is_empty((ann_a[rid].get("fields") or {}).get(field)) !=
                   is_empty((ann_b[rid].get("fields") or {}).get(field)))) / len(ids) if ids else None,
            "kappa_all": kappa(pairs_all),
            "kappa_valued": kappa(pairs_valued),
            "kappa_union": kappa(pairs_union),
            "numeric_exact_rate": (both_equal_valued / n_both) if (field in NUMERIC and n_both) else None,
            "numeric_exact_rate_union": (both_equal_valued / len(pairs_union))
                if (field in NUMERIC and pairs_union) else None,
        }

    for rid in ids:
        text = norm_text(pilot.get(rid, {}).get("text_full", ""))
        for side, ann in (("A", ann_a[rid]), ("B", ann_b[rid])):
            for field, judg in (ann.get("fields") or {}).items():
                if is_empty(judg):
                    continue
                for q in judg.get("evidence") or []:
                    evidence_total += 1
                    if norm_text(q) and norm_text(q) in text:
                        evidence_hit += 1

    # 现行 G0.3 口径：分类 κ 在"至少一方有值"的记录对上计算（kappa_union）
    key_cat_union = [f for f in KEY_CATEGORICAL if per_field[f]["kappa_union"] is not None]
    gate_kappa_union = (sum(per_field[f]["kappa_union"] for f in key_cat_union) / len(key_cat_union)) if key_cat_union else None
    key_cat = [f for f in KEY_CATEGORICAL if per_field[f]["kappa_all"] is not None]
    key_num_pairs = sum(per_field[f]["n_union_valued"] for f in KEY_NUMERIC)
    key_num_equal = sum(
        (per_field[f]["numeric_exact_rate"] or 0.0) * per_field[f]["n_both_valued"] for f in KEY_NUMERIC
    )
    key_num_both_pairs = sum(per_field[f]["n_both_valued"] for f in KEY_NUMERIC)
    key_numeric_fields_covered = [f for f in KEY_NUMERIC if per_field[f]["n_union_valued"] > 0]
    gate_kappa = (sum(per_field[f]["kappa_all"] for f in key_cat) / len(key_cat)) if key_cat else None
    gate_numeric = (key_num_equal / key_num_pairs) if key_num_pairs else None
    gate_numeric_both = (key_num_equal / key_num_both_pairs) if key_num_both_pairs else None

    report = {
        "annotators": {"A": str(path_a), "B": str(path_b)},
        "input": str(path_pilot),
        "n_records": len(ids),
        "missing_ids": sorted(missing),
        "extra_ids": sorted(extra),
        "gate_G0_3": {
            "key_categorical_mean_kappa_union": gate_kappa_union,
            "key_categorical_fields_used_union": key_cat_union,
            "key_categorical_mean_kappa_all": gate_kappa,
            "key_categorical_fields_used": key_cat,
            "key_numeric_exact_rate": gate_numeric,
            "key_numeric_pairs": key_num_pairs,
            "key_numeric_exact_rate_both_valued_reference": gate_numeric_both,
            "key_numeric_both_valued_pairs": key_num_both_pairs,
            "key_numeric_fields_covered": key_numeric_fields_covered,
            "threshold_kappa": 0.80,
            "threshold_numeric": 0.95,
            "primary_kappa_metric": "kappa_union（现行 G0.3：至少一方有值字段口径）",
            "pass": bool(not missing and not extra and len(ids) == len(pilot)
                         and len(key_cat_union) == len(KEY_CATEGORICAL)
                         and len(key_numeric_fields_covered) == len(KEY_NUMERIC)
                         and gate_kappa_union is not None and gate_kappa_union >= 0.80
                         and gate_numeric is not None and gate_numeric >= 0.95),
        },
        "evidence": {"total_quotes": evidence_total, "verbatim_hits": evidence_hit,
                     "hit_rate": (evidence_hit / evidence_total) if evidence_total else None},
        "n_disagreements": len(disagreements),
        "per_field": per_field,
    }

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "agreement_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    with (outdir / "disagreements.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "field", "type", "a_status", "a_value", "b_status", "b_value"])
        w.writeheader()
        w.writerows(disagreements)

    lines = [
        "# 试标一致性报告（G0.3 口径）", "",
        f"- 记录数 {len(ids)}（缺失 {sorted(missing) or '无'}；多余 {sorted(extra) or '无'}）",
        f"- 关键分类字段 mean κ(union，至少一方有值) = **{gate_kappa_union}**（门槛 0.80；参与字段：{key_cat_union}）",
        f"- 关键分类字段 mean κ(all，未提及计类别) = {gate_kappa}（参考口径）",
        f"- 关键数值字段完全一致率（union） = **{gate_numeric}**（{key_num_pairs} 对；门槛 0.95）",
        f"- 关键数值字段完全一致率（双方有值，仅参考） = {gate_numeric_both}（{key_num_both_pairs} 对）",
        f"- 门禁 G0.3 判定：**{'通过' if report['gate_G0_3']['pass'] else '不通过'}**",
        f"- 证据逐字命中 {evidence_hit}/{evidence_total} = {report['evidence']['hit_rate']}",
        f"- 分歧条目 {len(disagreements)} 条，见 disagreements.csv", "",
        "| 字段 | 类型 | 关键 | 双有值 | 至少一方有值 | κ(all) | κ(valued) | κ(union) | 数值一致率（双有值） | 数值一致率（union） | 在场一致 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for field, s in per_field.items():
        lines.append(
            f"| {field} | {s['type']} | {'★' if s['key'] else ''} | {s['n_both_valued']} | "
            f"{s['n_union_valued']} | "
            f"{s['kappa_all'] if s['kappa_all'] is not None else '—'} | "
            f"{s['kappa_valued'] if s['kappa_valued'] is not None else '—'} | "
            f"{s['kappa_union'] if s['kappa_union'] is not None else '—'} | "
            f"{s['numeric_exact_rate'] if s['numeric_exact_rate'] is not None else '—'} | "
            f"{s['numeric_exact_rate_union'] if s['numeric_exact_rate_union'] is not None else '—'} | "
            f"{s['presence_agreement']:.3f} |"
        )
    (outdir / "agreement_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report["gate_G0_3"], ensure_ascii=False, indent=1))
    print(f"report -> {outdir / 'agreement_report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

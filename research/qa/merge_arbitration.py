"""仲裁合并（金标质检线）：把仲裁决定合并进标注员 A 的原标，产出仲裁后标签与仲裁台账。

用法：python merge_arbitration.py <A目录或.jsonl> <仲裁决定.jsonl> <pilot50.jsonl> <输出目录>
仲裁决定每行一个 JSON：{"id":..., "field":..., "decision": "A"|"B"|"未提及"|"新值",
                        "value": <任意 JSON 或 null>, "status": "明确"|"推断"|"未提及",
                        "evidence": ["…"], "reason": "一句话理由"}
输出：outdir/arbitrated.jsonl（以 A 为基座、按决定覆盖字段）、outdir/arbitration_log.csv、
      outdir/arbitration_stats.json（按 decision 与字段统计）。
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path


def load_jsonl(p: Path) -> list[dict]:
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    out = []
    for fp in files:
        for line in fp.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    path_a, path_dec, path_pilot, outdir = Path(argv[1]), Path(argv[2]), Path(argv[3]), Path(argv[4])

    anns = {r["id"]: r for r in load_jsonl(path_a)}
    decisions = load_jsonl(path_dec)
    pilot_ids = {json.loads(l)["id"] for l in path_pilot.read_text(encoding="utf-8-sig").splitlines() if l.strip()}

    applied = 0
    problems: list[str] = []
    by_decision: Counter = Counter()
    by_field: Counter = Counter()
    log_rows: list[dict] = []
    for d in decisions:
        rid, field = d.get("id"), d.get("field")
        if rid not in anns:
            problems.append(f"id 不存在: {rid}")
            continue
        if field not in anns[rid].get("fields", {}):
            problems.append(f"字段不存在: {rid}.{field}")
            continue
        dec = d.get("decision")
        by_decision[dec] += 1
        by_field[field] += 1
        target = anns[rid]["fields"][field]
        if dec == "A":
            pass
        elif dec == "B":
            target["adopted_from"] = "B"
        elif dec == "未提及":
            target.clear()
            target.update({"value": None, "status": "未提及", "evidence": []})
        elif dec == "新值":
            target.clear()
            target.update({"value": d.get("value"), "status": d.get("status") or "推断",
                           "evidence": d.get("evidence") or [], "confidence": None,
                           "adopted_from": "仲裁"})
        else:
            problems.append(f"未知 decision: {dec} @ {rid}.{field}")
            continue
        applied += 1
        log_rows.append({"id": rid, "field": field, "decision": dec,
                         "reason": d.get("reason", ""), "a_value": json.dumps(target.get("value"), ensure_ascii=False)})

    missing_ids = pilot_ids - set(anns)
    if missing_ids:
        problems.append(f"仲裁后仍缺记录: {sorted(missing_ids)}")

    outdir.mkdir(parents=True, exist_ok=True)
    with (outdir / "arbitrated.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for rid in sorted(anns, key=lambda i: (i not in pilot_ids, i)):
            f.write(json.dumps(anns[rid], ensure_ascii=False) + "\n")
    with (outdir / "arbitration_log.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "field", "decision", "reason", "a_value"])
        w.writeheader()
        w.writerows(log_rows)
    stats = {"n_decisions": len(decisions), "n_applied": applied,
             "by_decision": dict(by_decision), "top_fields": by_field.most_common(20),
             "problems": problems}
    (outdir / "arbitration_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("n_decisions", "n_applied", "by_decision", "problems")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""历史锚对照（协同指令 2026-10-17 §7，免费全量）：S1 字段 vs parsed-1 regex 字段逐字段对照。

对照字段：outcome.type / fine / detention_days / not_executed / behavior_date / decision_date。
S1 的日期只有引文——从引文提取日期值后对照；S1 fine 遮蔽件（fine_masked）跳过对照。
**使用纪律（指令 §7）：regex 产出是参照不是真值**——分歧集交仲裁模块，法律锚优先。

用法：
  python research/discretion/unify/anchor_compare.py \
      --batch <parsed-1 records.jsonl> --run <s1_runs/<id>> --out <dir>
产物：divergences.csv（id/字段/S1值/regex值）+ agreement_stats.json。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

FIELDS = ["outcome.type", "fine", "detention_days", "not_executed",
          "behavior_date", "decision_date"]

_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日|(\d{4})年(\d{1,2})月")


def date_from_quote(quote: str | None) -> str:
    """S1 日期引文 → YYYY-MM-DD（只到月记 YYYY-MM）。引文里出现多个日期取首个。"""
    if not quote:
        return ""
    m = _DATE.search(quote)
    if not m:
        return ""
    if m.group(1):
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return f"{m.group(4)}-{int(m.group(5)):02d}"


def s1_values(out: dict) -> dict:
    oc = out.get("outcome") or {}
    dates = out.get("dates") or {}
    ne = oc.get("not_executed")
    return {
        "outcome.type": oc.get("type") or "",
        "fine": oc.get("fine") if oc.get("fine") is not None else 0,
        "detention_days": oc.get("detention_days") if oc.get("detention_days") is not None else 0,
        "not_executed": ne or "",
        "behavior_date": date_from_quote((dates.get("behavior") or {}).get("quote")),
        "decision_date": date_from_quote((dates.get("decision") or {}).get("quote")),
    }


def anchor_values(rec: dict) -> dict:
    oc = rec.get("outcome") or {}
    return {
        "outcome.type": oc.get("type") or "",
        "fine": oc.get("fine") if oc.get("fine") is not None else 0,
        "detention_days": oc.get("detention_days") if oc.get("detention_days") is not None else 0,
        "not_executed": oc.get("detention_not_executed") or "",
        "behavior_date": rec.get("behavior_date") or "",
        "decision_date": rec.get("decision_date") or "",
    }


def norm_date(s: str) -> str:
    """parsed-1 日期可能只到月/带日——对照统一截到月（引文有日的记日历但仍按月对齐宽口径）。"""
    s = s or ""
    if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", s):
        return s[:7]
    return s


def comparable(field: str, a, b) -> bool:
    if field in ("behavior_date", "decision_date"):
        return bool(norm_date(a) and norm_date(b))
    if field == "not_executed":
        return bool(a) and bool(b)
    return True


def equal(field: str, a, b) -> bool:
    if field in ("behavior_date", "decision_date"):
        return norm_date(a) == norm_date(b)
    try:
        if field in ("fine", "detention_days"):
            return abs(float(a or 0) - float(b or 0)) < 1e-6
    except (TypeError, ValueError):
        return False
    return a == b


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    recs = {r["id"]: r for r in (json.loads(l) for l in open(a.batch, encoding="utf-8"))}
    outs = [json.loads(l) for l in open(Path(a.run) / "outputs.jsonl", encoding="utf-8")]
    outs = [o for o in outs if o.get("ok")]

    agree = Counter()
    total = Counter()
    divergences = []
    for o in outs:
        rec = recs.get(o["id"])
        if rec is None:
            continue
        if (o["output"].get("outcome") or {}).get("fine_masked"):
            continue   # 遮蔽金额件：S1 按纪律不猜金额，跳过对照
        sv, av = s1_values(o["output"]), anchor_values(rec)
        for fld in FIELDS:
            if not comparable(fld, sv[fld], av[fld]):
                continue
            total[fld] += 1
            if equal(fld, sv[fld], av[fld]):
                agree[fld] += 1
            else:
                divergences.append({"id": o["id"], "field": fld,
                                    "s1": json.dumps(sv[fld], ensure_ascii=False),
                                    "anchor": json.dumps(av[fld], ensure_ascii=False)})

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "divergences.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "field", "s1", "anchor"])
        w.writeheader()
        w.writerows(divergences)
    stats = {
        "n_records": len(outs), "n_divergences": len(divergences),
        "by_field": {fld: {"total": total[fld], "agree": agree[fld],
                           "agree_rate": round(agree[fld] / total[fld], 4) if total[fld] else None}
                     for fld in FIELDS},
        "note": "regex 为参照非真值（指令 §7）；分歧件进仲裁，法律锚优先",
    }
    (out / "agreement_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""交付版本全量问题测试（parse 层 QC 电池）：对交付文件逐件跑检查注册表，输出分组统计与逐件标记 CSV。

范围：admin_cases（全检查）+ admin_outcomes_only（仅结果/元数据检查，无事实段要求）。
检查注册表 CHECKS：每项 (id, 说明, 严重级, 适用文件, 判定函数)。判定只依赖交付字段，解析器无关——
网页与法宝同一把尺子。输出：控制台分组统计（按检查×来源类型×省），--csv 写逐件标记明细。

用法（仓库根目录）：
  python research/discretion/harvest/parse_qc.py --version 2026-10-16.r5 [--csv out.csv] [--source 网页,法宝]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "discover"))
from search import data_root  # noqa: E402

CONCL_TAIL = re.compile(r"[^。；]*?(?:行为|其)?已?经?构成[^。]*(?:违法|犯罪|行为)[^。]*。?\s*$|属于(?:情节较重|情节严重|一般违法)[^。]*。?\s*$")
CONCL_ANY = re.compile(r"(?:行为|其)?已?经?构成[^。]*|属于(?:情节较重|情节严重|一般违法)")
EVID_PAT = re.compile(r"等证据(?:予以)?证实|询问笔录|讯问笔录|陈述和申辩|检查笔录|证据保全")
GENJV = re.compile(r"根据《")
LAW82 = re.compile(r"第八十二条")
LAW70 = re.compile(r"第七十条")
SEV = {"硬": 0, "疑": 1}


def _facts(rec):
    return (rec.get("text_facts") or "").strip()


def _seg(rec):
    return bool(rec.get("segmented"))


# 每个检查：(key, 说明, 级别, 适用文件集, 判定→返回命中窗口或 None)；rec 为交付记录
def _make_checks():
    def c_concl_tail(rec):
        f = _facts(rec)
        m = CONCL_TAIL.search(f)
        return m and ("定性句收尾", f[max(0, m.start() - 10):])

    def c_concl_any(rec):
        f = _facts(rec)
        if CONCL_TAIL.search(f):
            return None
        m = CONCL_ANY.search(f)
        return m and ("定性句段中", f[max(0, m.start() - 10): m.end() + 6])

    def c_evid_in_facts(rec):
        f = _facts(rec)
        m = EVID_PAT.search(f)
        return m and ("证据句混入", f[max(0, m.start() - 12): min(len(f), m.end() + 10)])

    def c_genjv_in_facts(rec):
        f = _facts(rec)
        m = GENJV.search(f)
        return m and ("事实段含根据法条", f[max(0, m.start() - 6): m.end() + 12])

    def c_tail_comma(rec):
        f = _facts(rec)
        return (f.endswith(("，", "、", "；")) and (len(f) >= 30 or None)) and ("逗号截尾", f[-14:]) or None

    def c_tail_han(rec):
        f = _facts(rec)
        if f and f[-1] not in "。；：）」】" and not f.endswith(("，", "、")):
            return ("非句读截尾", f[-12:])
        return None

    def c_short(rec):
        f = _facts(rec)
        return (0 < len(f) < 30) and ("事实段<30字", f)

    def c_empty_facts(rec):
        return not _facts(rec) and ("事实段为空", "")

    def c_facts_eq_full(rec):
        f, t = _facts(rec), (rec.get("text_full") or "").strip()
        return (f and t and f == t) and ("事实段=全文", f[:20])

    def c_law_mismatch(rec):
        """D8：以引用法条的版本注解为准。（2025修订）的第七十条也是新法——不看注解会把 P-763 类误报。"""
        oc, lv, d = rec.get("outcome") or {}, rec.get("law_version"), (rec.get("text_decision") or "") + (rec.get("text_reasoning") or "") + (rec.get("text_facts") or "")
        arts = "，".join(oc.get("articles") or [])
        has_new_82 = "第八十二条" in arts or ("第八十二条" in d and "不再适用" not in d[max(0, d.find("第八十二条") - 30): d.find("第八十二条")])
        if has_new_82 and lv == "旧法":
            return ("引用82条但标旧法", (arts or "articles为空")[:30])
        if "（2012修正）" in arts and lv == "新法":
            return ("2012版条但标新法", arts[:30])
        if arts and "（2025修订）" in arts and "第七十条" in arts and "第八十二条" not in arts and lv == "新法":
            return None  # 2025修订的第七十条：新法口径，一致
        return None

    def c_type_amount(rec):
        oc = rec.get("outcome") or {}
        t = oc.get("type") or ""
        if "拘留" in t and not oc.get("detention_days"):
            return ("类型与天数矛盾", t)
        if "罚款" in t and not oc.get("fine"):
            return ("类型与罚款矛盾", t)
        return None

    def c_date_order(rec):
        b, dd = rec.get("behavior_date") or "", rec.get("decision_date") or ""
        if b and dd and b[:10] > dd[:10] and b[:4] == dd[:4]:
            return ("行为晚于决定", f"{b}>{dd}")
        return None

    def c_no_event(rec):
        return (not rec.get("event_key") and not rec.get("event_id")) and ("无事件键", "")

    def c_unseg_anchor(rec):
        t = rec.get("text_full") or ""
        if not _seg(rec) and re.search(r"现查明|经查明|经查实", t):
            m = re.search(r"现查明|经查明|经查实", t)
            return ("有锚点未分段", t[max(0, m.start() - 8): m.start() + 24])
        return None

    def c_unseg_full(rec):
        t = (rec.get("text_full") or "").strip()
        if not _seg(rec) and _facts(rec) and _facts(rec) == t and len(t) > 120:
            return ("未分段且事实段=全文", t[:24])
        return None

    return [
        ("concl_tail", "定性句收尾", "疑", ("cases",), c_concl_tail),
        ("concl_any", "定性句段中", "疑", ("cases",), c_concl_any),
        ("evid_in_facts", "证据句混入事实段", "疑", ("cases",), c_evid_in_facts),
        ("genjv_in_facts", "事实段含根据法条", "疑", ("cases",), c_genjv_in_facts),
        ("tail_comma", "事实段逗号截尾", "疑", ("cases",), c_tail_comma),
        ("tail_han", "事实段非句读截尾", "疑", ("cases",), c_tail_han),
        ("short_facts", "事实段<30字", "疑", ("cases",), c_short),
        ("empty_facts", "事实段为空", "硬", ("cases",), c_empty_facts),
        ("facts_eq_full", "事实段=全文", "硬", ("cases",), c_facts_eq_full),
        ("law_mismatch", "法条与版本矛盾", "硬", ("cases", "outcomes"), c_law_mismatch),
        ("type_amount", "类型与数额矛盾", "硬", ("cases", "outcomes"), c_type_amount),
        ("date_order", "行为晚于决定", "疑", ("cases", "outcomes"), c_date_order),
        ("no_event", "无事件键", "疑", ("cases", "outcomes"), c_no_event),
        ("unseg_anchor", "有锚点未分段", "硬", ("cases",), c_unseg_anchor),
        ("unseg_full", "未分段且事实段=全文", "硬", ("cases",), c_unseg_full),
    ]


CHECKS = _make_checks()


def main() -> int:
    ap = argparse.ArgumentParser(description="交付版本全量问题测试（parse QC 电池）")
    ap.add_argument("--version", default="", help="交付版本目录名（缺省 LATEST 指向）")
    ap.add_argument("--csv", default="", help="逐件标记明细输出 CSV 路径")
    ap.add_argument("--source", default="", help="按 source 前缀过滤（网页,法宝）")
    args = ap.parse_args()

    root = data_root().parent
    version = args.version or (root / "delivery" / "LATEST").read_text(encoding="utf-8").strip()
    src = {Path: None}
    base = root / "delivery" / version
    files = {"cases": base / "admin_cases.schema-1.0.0.jsonl", "outcomes": base / "admin_outcomes_only.jsonl"}
    src_filter = [s for s in args.source.split(",") if s] if args.source else None

    flagged = []
    stat = Counter()                                   # (check, kind, source_type) → count
    per_source = defaultdict(Counter)
    n_files = {}
    for kind, f in files.items():
        if not f.exists():
            continue
        recs = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        n_files[kind] = len(recs)
        for rec in recs:
            src_name = "网页" if rec.get("id", "").startswith("W") else "法宝"
            if src_filter and not any(rec.get("source", "").find(s) >= 0 or src_name == s for s in src_filter):
                continue
            rid, prov = rec["id"], rec.get("province") or "未知"
            for key, label, sev, kinds, fn in CHECKS:
                if kind not in kinds:
                    continue
                hit = fn(rec)
                if hit:
                    detail = (hit[1] or "")[:40]
                    flagged.append({"id": rid, "src": src_name, "source_type": rec.get("source_type", ""),
                                    "province": prov, "file": kind, "check": key, "label": label,
                                    "sev": sev, "detail": detail})
                    stat[(key, kind, rec.get("source_type", ""))] += 1
                    per_source[src_name][key] += 1

    print(f"# 版本 {version}：主文件 {n_files.get('cases', 0)} + 只有结果 {n_files.get('outcomes', 0)}")
    print(f"# {'检查组':<18}{'级':<3}{'主文件':>8}{'只有结果':>8}   主要来源类型")
    for key, label, sev, kinds, _ in CHECKS:
        rows = [(kind, st, n) for (k, kind, st), n in stat.items() if k == key]
        if not rows:
            continue
        total_cases = sum(n for kind, st, n in rows if kind == "cases")
        total_out = sum(n for kind, st, n in rows if kind == "outcomes")
        tops = Counter()
        for kind, st, n in rows:
            tops[st] += n
        top_str = "; ".join(f"{t}×{n}" for t, n in tops.most_common(3))
        print(f"  {label:<16}{sev:<3}{total_cases:>8}{total_out:>8}   {top_str}")
    print("# 按来源线：")
    for s, cc in per_source.items():
        print(f"  {s}: " + "; ".join(f"{k}×{n}" for k, n in cc.most_common(8)))
    print(f"# 逐件标记合计 {len(flagged)} 行（去重前）")
    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["id", "src", "source_type", "province", "file", "check", "label", "sev", "detail"])
            w.writeheader()
            w.writerows(flagged)
        print(f"# 明细 → {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

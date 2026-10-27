"""WP2 B-Hist 噪声天花板 v1（执行计划 2026-10-27 §1 WP2 预注册规格的首跑）。

两层离散度：
- L1 同事件跨人（同机关/同日/同现场，facts 近同）→ 同事实裁量噪声（噪声下界证据）；
- L2 同层跨事件（省 × 处罚类型档，mechanism=base）→ 实务离散度（模型必须解释的部分）。

指标：拘留天数 pairwise |Δ| 中位数（有拘留者）；罚款对数比 |ln(f1/f2)| 中位数与 ±20% 内
比例（有罚款者）；处罚类型不一致率。bootstrap percentile 1000 次；n≥50 才报告（D-004 口径）。

门禁映射（机械判定，不修订门槛）：
- G3.5 天数 MAE≤1.5：L1 中位 |Δ天| > 1.5 → 同事实层已超阈；L1≤1.5<L2 → 临界；两层≤1.5 → 未超。
- G3.6 罚款 ±20%≥0.75：L1 ±20% 内比例 < 0.75 → 同事实层已超阈；L1≥0.75>L2 → 临界。
- G3.4/G3.2：L1 类型不一致率 = 事实近同而结论不同的份额（类型准确率噪声证据，非形式上界）。

v1 范围声明：预注册全规格的 L2 键含行为类型/赌博方式/赌资带（近重复细化），v1 先以 省×档 落地，
近重复细化随 WP3② M2 档位特征补做——结论按 v1 口径引用。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics as st
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from outcome_constraint_calibration import resolve_regions

TIER_BY_TYPE = {"罚款": 1, "拘留": 2, "拘留并处罚款": 3}
TIER_NAME = {1: "罚款档", 2: "拘留档", 3: "并罚档"}
GATE_MAE, GATE_PCT20 = 1.5, 0.75


def boot_ci(values: list, stat=st.median, n_boot: int = 1000, seed: int = 42) -> list | None:
    if len(values) < 30:
        return None
    rng = random.Random(seed)
    reps = []
    for _ in range(n_boot):
        reps.append(stat([values[rng.randrange(len(values))] for _ in range(len(values))]))
    reps.sort()
    return [reps[int(0.025 * n_boot)], reps[int(0.975 * n_boot) - 1]]


def to_metrics(pairs: list, label: str) -> dict:
    """pairs = [(rec_x, rec_y), ...]，直接从记录对取三目标。"""
    d = [abs(x["target"]["detention_days"] - y["target"]["detention_days"])
         for x, y in pairs if x["target"]["detention_days"] > 0 and y["target"]["detention_days"] > 0]
    fines = [(x["target"]["fine"], y["target"]["fine"]) for x, y in pairs
             if x["target"]["fine"] > 0 and y["target"]["fine"] > 0]
    lr = [abs(math.log(hi / lo)) for lo, hi in ((min(f, g), max(f, g)) for f, g in fines)]
    ok20 = [hi / lo <= 1.25 for lo, hi in ((min(f, g), max(f, g)) for f, g in fines)]
    mism = sum(1 for x, y in pairs if x["target"]["type"] != y["target"]["type"])
    return {
        "label": label, "n_pairs": len(pairs),
        "days_n": len(d),
        "days_med_absdiff": st.median(d) if d else None,
        "days_ci95": boot_ci(d) if d else None,
        "fine_n": len(fines),
        "fine_logratio_med": st.median(lr) if lr else None,
        "fine_within20pct": (sum(ok20) / len(ok20)) if ok20 else None,
        "type_mismatch_rate": (mism / len(pairs)) if pairs else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default=r"D:/02_Dev/Data/justilaw-research/engine/training/m4-facts-silver-1740-v3-clean-20261026")
    ap.add_argument("--lake-db", default=r"D:/02_Dev/Data/justilaw-research/lake/catalog/lake.db")
    ap.add_argument("--out", default=r"D:/02_Dev/Data/justilaw-research/engine/development/b-hist-ceiling-20261027")
    ap.add_argument("--max-l2-pairs", type=int, default=4000)
    a = ap.parse_args()
    pkg, out = Path(a.package), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    train = [json.loads(l) for l in (pkg / "train.jsonl").open(encoding="utf-8")]
    regions = resolve_regions(train, Path(a.lake_db))

    for r in train:
        r["_prov"] = regions.get(r["id"]) or "未知省"
        r["_tier"] = TIER_BY_TYPE.get(r["target"]["type"])

    # ---------- L1 同事件跨人 ----------
    by_event = defaultdict(list)
    for r in train:
        by_event[r["event_id"]].append(r)
    multi = {e: rs for e, rs in by_event.items() if len(rs) >= 2}

    l1_pairs = []  # (rec_a, rec_b)
    l1_base_pairs = []
    for rs in multi.values():
        for x, y in combinations(rs, 2):
            l1_pairs.append((x, y))
            if x["metadata"].get("mechanism") == "base" and y["metadata"].get("mechanism") == "base":
                l1_base_pairs.append((x, y))

    l1_all = to_metrics(l1_pairs, "L1 同事件跨人（全 mechanism）")
    l1_base = to_metrics(l1_base_pairs, "L1 同事件跨人（双方 base）")

    l1_by_tier = {}
    for tier in (1, 2, 3):
        ps = [(x, y) for x, y in l1_base_pairs if x["_tier"] == tier and y["_tier"] == tier]
        # 同事件双方同档的配对才有"同事实不同后果"之外的干净读数；跨档配对计入类型不一致
        if len(ps) >= 30:
            l1_by_tier[TIER_NAME[tier]] = to_metrics(ps, f"L1 {TIER_NAME[tier]}（双方 base 同档）")

    l1_cross = [(x, y) for x, y in l1_base_pairs if x["_tier"] != y["_tier"]]
    l1_cross_rate = len(l1_cross) / len(l1_base_pairs) if l1_base_pairs else None

    # ---------- L2 同层跨事件（省 × 档, base）----------
    rng = random.Random(42)
    l2 = {}
    strata = defaultdict(list)
    for r in train:
        if r["metadata"].get("mechanism") != "base" or r["_tier"] is None:
            continue
        strata[(r["_prov"], r["_tier"])].append(r)
        strata[("全部省份", r["_tier"])].append(r)
    for (prov, tier), rs in strata.items():
        if len(rs) < 50:  # D-004：n≥50 才报告
            continue
        n_pairs = min(len(rs) * (len(rs) - 1) // 2, a.max_l2_pairs)
        pairs = []
        for _ in range(n_pairs):
            x, y = rng.sample(rs, 2)
            pairs.append((x, y))
        m = to_metrics(pairs, f"L2 {prov}·{TIER_NAME[tier]}（跨事件, base）")
        m["n_records"] = len(rs)
        l2[f"{prov}·{TIER_NAME[tier]}"] = m

    # ---------- 门禁映射（机械判定）----------
    def verdict_mae(l1_med, l2_med):
        if l1_med is not None and l1_med > GATE_MAE:
            return "同事实层已超阈"
        if l2_med is not None and l2_med > GATE_MAE:
            return "临界（跨事件超阈/同事实未超）"
        return "两层未超"

    def verdict_p20(l1_ok, l2_ok):
        if l1_ok is not None and l1_ok < GATE_PCT20:
            return "同事实层已超阈"
        if l2_ok is not None and l2_ok < GATE_PCT20:
            return "临界（跨事件超阈/同事实未超）"
        return "两层未超"

    gates = []
    for tier in (1, 2, 3):
        name = TIER_NAME[tier]
        l1m = l1_by_tier.get(name)
        l2m = l2.get(f"全部省份·{name}")
        gates.append({
            "stratum": name,
            "G3.5_MAE≤1.5": {
                "L1_med_absdays": l1m and l1m["days_med_absdiff"], "L2_med_absdays": l2m and l2m["days_med_absdiff"],
                "verdict": verdict_mae(l1m and l1m["days_med_absdiff"], l2m and l2m["days_med_absdiff"]),
            },
            "G3.6_±20%≥0.75": {
                "L1_within20": l1m and l1m["fine_within20pct"], "L2_within20": l2m and l2m["fine_within20pct"],
                "verdict": verdict_p20(l1m and l1m["fine_within20pct"], l2m and l2m["fine_within20pct"]),
            },
        })
    type_noise = {
        "L1_type_mismatch_base": l1_base["type_mismatch_rate"],
        "L1_cross_tier_rate_base": l1_cross_rate,
        "note": "同事件跨人类型不一致率=事实近同而结论不同的份额；跨档率含事实外的角色/情节差，非形式上界",
    }

    report = {
        "package": str(pkg), "records": len(train),
        "events": len(by_event), "multi_record_events": len(multi),
        "L1": {"all": l1_all, "base": l1_base, "by_tier": l1_by_tier}, "L2": l2,
        "gates": gates, "type_noise": type_noise,
        "method": "L1=同事件跨人配对(噪声下界证据); L2=省×档跨事件随机配对≤4000(实务离散); bootstrap percentile 1000, n≥30 出CI, 层n≥50 报告; v1=省×档, 近重复细化随WP3②",
        "provinces_in_scope": dict(Counter(r["_prov"] for r in train)),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# B-Hist 噪声天花板 v1（自动生成）", "",
             f"包：{pkg}（{len(train)} 条 / {len(by_event)} 事件 / 多记录事件 {len(multi)}）", ""]
    lines += ["## L1 同事件跨人", "",
              f"- 全 mechanism 配对 {l1_all['n_pairs']}：天数|Δ|中位 {l1_all['days_med_absdiff']}（n={l1_all['days_n']}），罚款±20%内 {l1_all['fine_within20pct']}（n={l1_all['fine_n']}），类型不一致率 {l1_all['type_mismatch_rate']}",
              f"- 双方 base 配对 {l1_base['n_pairs']}：天数|Δ|中位 {l1_base['days_med_absdiff']}（n={l1_base['days_n']}），罚款±20%内 {l1_base['fine_within20pct']}（n={l1_base['fine_n']}），类型不一致率 {l1_base['type_mismatch_rate']}，跨档率 {l1_cross_rate}", ""]
    lines += ["## 门禁映射（机械判定）", "", "| 层 | G3.5 L1中位|Δ天| | G3.5 L2中位|Δ天| | G3.5 判定 | G3.6 L1 ±20% | G3.6 L2 ±20% | G3.6 判定 |", "|---|---|---|---|---|---|---|"]
    for g in gates:
        g5, g6 = g["G3.5_MAE≤1.5"], g["G3.6_±20%≥0.75"]
        lines.append(f"| {g['stratum']} | {g5['L1_med_absdays']} | {g5['L2_med_absdays']} | {g5['verdict']} | {g6['L1_within20']} | {g6['L2_within20']} | {g6['verdict']} |")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"L1_base": {k: l1_base[k] for k in ("n_pairs", "days_med_absdiff", "fine_within20pct", "type_mismatch_rate")},
                      "L1_by_tier": {k: v["days_med_absdiff"] for k, v in l1_by_tier.items()},
                      "gates": gates}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

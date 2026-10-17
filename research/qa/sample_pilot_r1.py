"""pilot50-v2 抽样（金标质检线）：从 r1 交付主文件按事件分层抽 50 件试标输入。

依据：阶段审查 2026-10-16 21:12——旧 pilot50 基于 harvest-0.4，对照 r1 已断层
（10 件移入 only、3 件正文哈希变化），须按 r1 主文件哈希重新分层抽样。
规则沿用 harvest/sample_pilot.py 口径（该脚本归网页线所有，此为其 r1 版复刻；
差异：目标省改为 河北+江苏；新法下限按现存实量全收）。

输出（金标线数据目录，不改 admin/）：
  $JUSTILAW_DATA_DIR/qa/pilot50-r1/input/pilot50-v2.jsonl
  $JUSTILAW_DATA_DIR/qa/pilot50-r1/pilot50-v2.stats.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

DATA = Path(r"D:\02_Dev\Data\justilaw-research")
R1 = DATA / "delivery" / "2026-10-16.r1" / "admin_cases.schema-1.0.0.jsonl"
OUTDIR = DATA / "qa" / "pilot50-r1"

SEED = "justilaw-pilot50-r1-2026-10-16"
TARGET_PROVINCES = ("河北省", "江苏省")
TARGET_BOOST = 2
TARGET_PROVINCE_MIN = 5
OTHER = "其他"
PILOT_FIELDS = ("id", "event_id", "subject_alias", "source_type", "behavior_date", "law_version",
                "schema_version", "text_full", "text_sha256", "text_facts", "text_evidence",
                "text_reasoning", "text_decision", "text_review", "segments", "outcome", "review")


def h(s: str) -> str:
    return hashlib.sha256((SEED + ":" + s).encode("utf-8")).hexdigest()


def eligible(r: dict) -> bool:
    q = r.get("quality") or {}
    return not q.get("ambiguous_persons") and not q.get("subject_variants")


def has_amount(r: dict) -> bool:
    return bool(((r.get("quality") or {}).get("completeness") or {}).get("has_amount"))


def main() -> int:
    recs = [json.loads(l) for l in R1.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_event: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        if eligible(r):
            by_event[r["event_id"]].append(r)

    # 事件代表：不予处罚 > 有金额 > 种子哈希
    reps = {}
    for eid, group in by_event.items():
        group = sorted(group, key=lambda r: (
            0 if (r.get("outcome") or {}).get("type") == "不予处罚" else 1,
            0 if has_amount(r) else 1,
            h(r["id"]),
        ))
        reps[eid] = group[0]

    prov_events: dict[str, int] = defaultdict(int)
    for r in reps.values():
        prov_events[r.get("province") or OTHER] += 1

    def bucket(r: dict) -> str:
        p = r.get("province") or OTHER
        if p in TARGET_PROVINCES:
            return p
        return p if prov_events[p] >= 10 else OTHER

    strata: dict[tuple, list[str]] = defaultdict(list)
    for eid, r in reps.items():
        strata[(bucket(r), r.get("source_type") or "其他", r.get("law_version") or "未知")].append(eid)

    weights = {}
    for key, eids in strata.items():
        w = len(eids)
        if key[0] in TARGET_PROVINCES:
            w *= TARGET_BOOST
        weights[key] = w
    wsum = sum(weights.values())
    raw = {k: 50 * w / wsum for k, w in weights.items()}
    quota = {k: min(max(1, int(v)), len(strata[k])) for k, v in raw.items()}
    assigned = sum(quota.values())
    for _, k in sorted(((raw[k] - quota[k], k) for k in quota), reverse=True):
        if assigned >= 50:
            break
        if quota[k] < len(strata[k]):
            quota[k] += 1
            assigned += 1
    while assigned > 50:
        k = max(quota, key=lambda k: quota[k])
        if quota[k] > 1:
            quota[k] -= 1
            assigned -= 1
        else:
            break

    # 目标省保底：从非目标省最大配额层平移（尊重各层事件数上限）
    for p in TARGET_PROVINCES:
        while sum(v for k, v in quota.items() if k[0] == p) < TARGET_PROVINCE_MIN:
            donors = sorted((k for k in quota if k[0] not in TARGET_PROVINCES and quota[k] > 1),
                            key=lambda k: -quota[k])
            moved = False
            for k in donors:
                take = min(1, len(strata[k]) - quota[k])
                if take <= 0:
                    continue
                quota[k] -= take
                tgt = next((t for t in quota if t[0] == p and quota[t] < len(strata[t])), None)
                if tgt is None:
                    quota[k] += take
                    continue
                quota[tgt] += take
                moved = True
                break
            if not moved:
                break

    must = [e for e, r in reps.items()
            if (r.get("law_version") or "") == "新法" or (r.get("outcome") or {}).get("type") == "不予处罚"]
    picked: list[str] = []
    picked_set = set()
    for k, eids in strata.items():
        eids_sorted = sorted(eids, key=lambda e: (
            0 if e in must else 1,
            0 if has_amount(reps[e]) else 1,
            h(e),
        ))
        for e in eids_sorted[: quota[k]]:
            if e not in picked_set:
                picked.append(e)
                picked_set.add(e)
    if len(picked) < 50:
        rest = sorted((e for e in reps if e not in picked_set), key=lambda e: h(e))
        picked.extend(rest[: 50 - len(picked)])
    picked = picked[:50]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "input").mkdir(exist_ok=True)
    out = OUTDIR / "input" / "pilot50-v2.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for e in picked:
            r = reps[e]
            f.write(json.dumps({k: r.get(k) for k in PILOT_FIELDS}, ensure_ascii=False) + "\n")

    dist = {"province": defaultdict(int), "source_type": defaultdict(int),
            "law_version": defaultdict(int), "has_amount": 0, "outcome_type": defaultdict(int)}
    for e in picked:
        r = reps[e]
        dist["province"][bucket(r)] += 1
        dist["source_type"][r.get("source_type") or "其他"] += 1
        dist["law_version"][r.get("law_version") or "未知"] += 1
        dist["has_amount"] += 1 if has_amount(r) else 0
        dist["outcome_type"][(r.get("outcome") or {}).get("type") or "?"] += 1

    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    stats = {
        "seed": SEED, "n": len(picked), "events": len(set(picked)),
        "input": str(R1), "input_sha256": hashlib.sha256(R1.read_bytes()).hexdigest(),
        "output": str(out), "output_sha256": sha,
        "eligible_records": sum(1 for r in recs if eligible(r)),
        "eligible_events": len(reps),
        "quota_table": {f"{k[0]}|{k[1]}|{k[2]}": {"events": len(strata[k]), "quota": quota[k]}
                        for k in sorted(strata)},
        "distribution": {"province": dict(dist["province"]), "source_type": dict(dist["source_type"]),
                         "law_version": dict(dist["law_version"]), "has_amount": dist["has_amount"],
                         "outcome_type": dict(dist["outcome_type"])},
        "ids": [reps[e]["id"] for e in picked],
        "note": "目标省河北+江苏；新法全收（r1 主文件仅 1 件新法，上游供给缺口如实体现）；"
                "旧 pilot50 可复用件以 qa/pilot50-r1-reuse/reuse-list.csv 为准，不与本样本混算。",
    }
    (OUTDIR / "pilot50-v2.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n": len(picked), "events": len(set(picked)),
                      "province": dict(dist["province"]), "law": dict(dist["law_version"]),
                      "has_amount": dist["has_amount"], "outcome": dict(dist["outcome_type"])},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""试标样本抽取：从金标候选里分层抽 50 件交数据链路与法律组双人试标（文本处理规范 docs/04-plan/text-processing-spec.md
§7 第 5 步、门禁 G0.3）。

规则：
  1. 可抽：`quality.ambiguous_persons` 为假且 `quality.subject_variants` 为 0（本人可唯一指认，双人标注才有可比性）。
  2. 一个事件只出一件：每个 `event_id` 先选一件代表（不予处罚 > 有金额 > 随机），层与配额都按事件数算，
     同一事件的多件不会同时进样本（同案多人在试标里只会抬高一致率）。
  3. 分层：省份 × 文书形态（source_type）× law_version（按行为日）。可抽事件少于 MIN_PROVINCE_EVENTS 的非目标省并为"其他"。
  4. 配额：按事件数比例分，目标省（TARGET_PROVINCES）权重 ×TARGET_BOOST；每层至少 1 件、新法合计至少 NEW_LAW_MIN 件、
     每个目标省合计至少 TARGET_PROVINCE_MIN 件、不予处罚全收；不超过该层可抽事件数。先定死触到下限或上限的层，
     其余按比例重分，最后用最大余数法取整。
  5. 层内：不予处罚 > 有金额（`quality.completeness.has_amount`）> 随机。随机数是 SHA-256(种子:id)，与输入顺序无关，可复现。

输出（外置数据目录，不入库）：
  $JUSTILAW_DATA_DIR/admin/pilot50.jsonl        标注需要的字段（PILOT_FIELDS），不含区划、质量标记等原文以外的信息
  $JUSTILAW_DATA_DIR/admin/pilot50.stats.json   种子、输入与输出的 SHA-256、各层配额、分布、id 清单（不含正文）
控制台打印分布表（Markdown），贴进文本处理规范 §8。

用法（仓库根目录）：python research/discretion/harvest/sample_pilot.py [--n 50] [--seed …]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "discover"))

from search import data_root  # noqa: E402

SEED = "justilaw-pilot50-2026-10-16"
TARGET_PROVINCES = ("安徽省", "云南省", "浙江省")
TARGET_BOOST = 2
TARGET_PROVINCE_MIN = 5
NEW_LAW_MIN = 5
MIN_PROVINCE_EVENTS = 10
OTHER = "其他"
MUST_OUTCOMES = ("不予处罚",)
PILOT_FIELDS = ("id", "event_id", "subject_alias", "source_type", "behavior_date", "law_version", "schema_version",
                "text_full", "text_sha256", "text_facts", "text_evidence", "text_reasoning", "text_decision",
                "text_review", "segments", "outcome", "review")
SOURCE_ORDER = {"处罚决定书": 0, "执法公示": 1, "行政复议决定书": 2}
LAW_ORDER = {"旧法": 0, "新法": 1, "未知": 2}


def eligible(rec: dict) -> bool:
    q = rec.get("quality") or {}
    return not q.get("ambiguous_persons") and not q.get("subject_variants")


def has_amount(rec: dict) -> bool:
    return bool(((rec.get("quality") or {}).get("completeness") or {}).get("has_amount"))


def is_must(rec: dict) -> bool:
    return (rec.get("outcome") or {}).get("type") in MUST_OUTCOMES


def rand_key(seed: str, rid: str) -> str:
    return hashlib.sha256(f"{seed}:{rid}".encode("utf-8")).hexdigest()


def preference(rec: dict, seed: str) -> tuple:
    """越小越优先：不予处罚 > 有金额 > 随机。"""
    return (not is_must(rec), not has_amount(rec), rand_key(seed, rec["id"]))


def representatives(pool: list[dict], seed: str) -> list[dict]:
    """每个 event_id 选一件代表；没有 event_id 的按自身成组。"""
    groups = defaultdict(list)
    for r in pool:
        groups[r.get("event_id") or r["id"]].append(r)
    return [min(g, key=lambda r: preference(r, seed)) for g in groups.values()]


def province_groups(reps: list[dict], targets=TARGET_PROVINCES, min_events=MIN_PROVINCE_EVENTS) -> dict[str, str]:
    n = Counter(r.get("province") or "" for r in reps)
    return {p: p if p and (p in targets or c >= min_events) else OTHER for p, c in n.items()}


def stratum_of(rec: dict, groups: dict[str, str]) -> tuple[str, str, str]:
    return (groups.get(rec.get("province") or "", OTHER), rec.get("source_type") or "", rec.get("law_version") or "未知")


def raise_floor(floor: dict, avail: dict, strata: list, minimum: int) -> None:
    """把 strata 的下限合计抬到 minimum（不超过可抽数），从可抽数多的层起轮流加 1。"""
    order = sorted(strata, key=lambda s: (-avail[s], s))
    while sum(floor[s] for s in strata) < minimum:
        room = [s for s in order if floor[s] < avail[s]]
        if not room:
            return
        for s in room:
            if sum(floor[s] for s in strata) >= minimum:
                break
            floor[s] += 1


def allocate(avail: dict, weight: dict, floor: dict, n: int) -> dict:
    """按权重比例把 n 分到各层：下限 floor、上限 avail；触限的层先定死，其余重分，最后最大余数取整。
    每轮先定死低于下限的层，没有了再定死超上限的层：这样剩余名额始终够剩余各层的下限。"""
    n = min(n, sum(avail.values()))
    floor = {s: min(floor.get(s, 0), avail[s]) for s in avail}
    if sum(floor.values()) > n:
        raise ValueError(f"各层下限合计 {sum(floor.values())} 超过样本量 {n}")
    alloc, free, left = {}, {s for s in avail if avail[s] > 0}, n
    for s in set(avail) - free:
        alloc[s] = 0
    while free:
        tw = sum(weight[s] for s in free)
        share = {s: left * weight[s] / tw if tw else 0.0 for s in free}
        fixed = {s: floor[s] for s in free if share[s] < floor[s]} or {s: avail[s] for s in free if share[s] > avail[s]}
        if not fixed:
            base = {s: int(share[s]) for s in free}
            extra = left - sum(base.values())
            for s in sorted(free, key=lambda s: (-(share[s] - base[s]), -weight[s], s))[:extra]:
                base[s] += 1
            alloc.update(base)
            break
        alloc.update(fixed)
        free -= fixed.keys()
        left -= sum(fixed.values())
    return alloc


def plan(records: list[dict], n: int = 50, seed: str = SEED) -> tuple[list[dict], dict]:
    """返回 (样本记录, 报告)。"""
    pool = [r for r in records if eligible(r)]
    reps = representatives(pool, seed)
    groups = province_groups(reps)
    by_stratum = defaultdict(list)
    for r in reps:
        by_stratum[stratum_of(r, groups)].append(r)
    avail = {s: len(v) for s, v in by_stratum.items()}
    weight = {s: avail[s] * (TARGET_BOOST if s[0] in TARGET_PROVINCES else 1) for s in avail}
    floor = {s: max(1, sum(is_must(r) for r in v)) for s, v in by_stratum.items()}
    raise_floor(floor, avail, [s for s in avail if s[2] == "新法"], NEW_LAW_MIN)
    for p in TARGET_PROVINCES:
        raise_floor(floor, avail, [s for s in avail if s[0] == p], TARGET_PROVINCE_MIN)
    quota = allocate(avail, weight, floor, n)
    picked = []
    for s, v in by_stratum.items():
        picked += sorted(v, key=lambda r: preference(r, seed))[:quota[s]]
    picked.sort(key=lambda r: r["id"])
    must_lost = sorted(r["id"] for r in records if is_must(r) and not eligible(r))
    report = {
        "seed": seed, "n": n,
        "input_records": len(records), "eligible_records": len(pool), "eligible_events": len(reps),
        "excluded": {"ambiguous_persons": sum(bool((r.get("quality") or {}).get("ambiguous_persons")) for r in records),
                     "subject_variants": sum(bool((r.get("quality") or {}).get("subject_variants")) for r in records)},
        "must_not_eligible": must_lost,
        "strata": [{"province": s[0], "source_type": s[1], "law_version": s[2], "events": avail[s],
                    "events_with_amount": sum(has_amount(r) for r in by_stratum[s]), "weight": weight[s],
                    "floor": floor[s], "quota": quota[s],
                    "picked_with_amount": sum(has_amount(r) for r in picked if stratum_of(r, groups) == s)}
                   for s in sorted(avail, key=stratum_sort_key(avail))],
        "distribution": distribution(picked),
        "ids": [r["id"] for r in picked],
    }
    return picked, report


def stratum_sort_key(avail: dict):
    """表格行序：目标省（按 TARGET_PROVINCES 顺序）→ 其余省按可抽事件数降序 → 其他；省内按形态、旧法在前。"""
    total = Counter()
    for s, c in avail.items():
        total[s[0]] += c

    def key(s: tuple) -> tuple:
        p, st, lv = s
        rank = TARGET_PROVINCES.index(p) if p in TARGET_PROVINCES else len(TARGET_PROVINCES)
        return (p == OTHER, rank, -total[p], p, SOURCE_ORDER.get(st, 9), LAW_ORDER.get(lv, 9))
    return key


def distribution(picked: list[dict]) -> dict:
    def count(f):
        return dict(Counter(f(r) for r in picked).most_common())
    return {
        "province": count(lambda r: r.get("province") or "未知"),
        "source_type": count(lambda r: r.get("source_type") or ""),
        "law_version": count(lambda r: r.get("law_version") or "未知"),
        "law_version_by_article": count(lambda r: (r.get("outcome") or {}).get("law_version") or "未知"),
        "has_amount": count(lambda r: "有金额" if has_amount(r) else "无金额"),
        "outcome_type": count(lambda r: (r.get("outcome") or {}).get("type") or "未解析"),
        "review": count(lambda r: (r.get("review") or {}).get("result") or "无"),
        "target_provinces": sum((r.get("province") or "") in TARGET_PROVINCES for r in picked),
        "events": len({r.get("event_id") for r in picked}),
    }


def pilot_record(rec: dict) -> dict:
    return {k: rec.get(k) for k in PILOT_FIELDS}


def markdown(report: dict) -> str:
    rows = ["| 省份 | 形态 | 新旧法（按行为日） | 可抽事件（有金额） | 配额 | 抽中有金额 |", "|---|---|---|---|---|---|"]
    for s in report["strata"]:
        rows.append(f"| {s['province']} | {s['source_type']} | {s['law_version']} | {s['events']}（{s['events_with_amount']}） "
                    f"| {s['quota']} | {s['picked_with_amount']} |")
    tot = report["strata"]
    rows.append(f"| **合计** | | | {sum(s['events'] for s in tot)}（{sum(s['events_with_amount'] for s in tot)}） "
                f"| **{sum(s['quota'] for s in tot)}** | {sum(s['picked_with_amount'] for s in tot)} |")
    d = report["distribution"]

    def line(label, c):
        return f"- {label}：" + "、".join(f"{k} {v}" for k, v in c.items())
    return "\n".join(rows + ["", line("省份", d["province"]), line("形态", d["source_type"]),
                             line("新旧法（按行为日）", d["law_version"]), line("新旧法（按所引条文）", d["law_version_by_article"]),
                             line("有无金额", d["has_amount"]), line("处罚类型", d["outcome_type"]),
                             line("复议结论", d["review"]),
                             f"- 目标省（{'、'.join(p.rstrip('省') for p in TARGET_PROVINCES)}）合计 {d['target_provinces']}；"
                             f"事件 {d['events']} 个（一事件一件）"])


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    adir = data_root().parent / "admin"
    ap = argparse.ArgumentParser(description="试标样本抽取（G0.3）")
    ap.add_argument("--input", type=Path, default=adir / "admin_cases.schema-1.0.0.jsonl")
    ap.add_argument("--out", type=Path, default=adir / "pilot50.jsonl")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", default=SEED)
    a = ap.parse_args(argv)
    records = [json.loads(l) for l in a.input.read_text(encoding="utf-8").splitlines() if l.strip()]
    picked, report = plan(records, a.n, a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in picked:
            f.write(json.dumps(pilot_record(r), ensure_ascii=False) + "\n")
    report = {"input": a.input.name, "input_sha256": sha256_file(a.input),
              "output": a.out.name, "output_sha256": sha256_file(a.out), **report}
    a.out.with_suffix(".stats.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"{len(picked)} 件 → {a.out}\n输入 {a.input.name} sha256 {report['input_sha256'][:16]}…\n")
    print(markdown(report))
    if report["must_not_eligible"]:
        print(f"\n注意：不予处罚但不可抽（本人无法区分或有多种写法）：{report['must_not_eligible']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

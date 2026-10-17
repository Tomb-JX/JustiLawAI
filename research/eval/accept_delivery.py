"""引擎侧交付验收（数据交付规格 §4）：逐条校验 + 批次校验 + 门禁差距，出验收报告。

运行：research/.venv/Scripts/python research/eval/accept_delivery.py [交付目录]
  交付目录默认 $JUSTILAW_DATA_DIR/admin（按版本发布后改为 delivery/<版本>/）。
报告写到 $JUSTILAW_DATA_DIR/engine/acceptance/<管线版本>-<主文件哈希前 8 位>/：
  acceptance.json（全部结果）、acceptance.md（一页摘要）、rejected.csv（退回的记录与原因）。

结论分三档：
  通过     —— 没有 error；
  部分通过 —— 只有记录级 error：这些记录退回，其余可进入标注；
  不通过   —— 有批次级 error（文件哈希不符、隐私扫描未过、编号重复等），整批退回。
门禁差距（完整度、新法件数、不予处罚件数……）单列，不影响结论，但决定还要补采什么。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "justilaw-api"))
from app.discretion import records as R  # noqa: E402
from app.discretion.schema import SCHEMA_VERSION  # noqa: E402

DATA = Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research"))
MAIN, ONLY = "admin_cases.schema-1.0.0.jsonl", "admin_outcomes_only.jsonl"
CHECKER_VERSION = "accept-0.1"
EVENT_SPREAD_DAYS = 31
# 门禁与规格 §2 的数量要求（只统计验收通过的主文件记录）
GATES = {"completeness": 0.80, "t_time": 50, "tier_each": 100, "gold_total": 500}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    rows, bad = [], []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    bad.append(f"第{i}行")
    return rows, bad


def batch_checks(folder: Path, files: dict[str, list[dict]]) -> list[dict]:
    out = []

    def add(level, code, message):
        out.append({"level": level, "code": code, "message": message})

    sums = folder / "SHA256SUMS"
    if not sums.exists():
        add("error", "sha256sums_missing", "缺少 SHA256SUMS")
    else:
        listed = {}
        for line in sums.read_text("utf-8").splitlines():
            if line.strip():
                digest, name = line.split(maxsplit=1)
                listed[name.strip().lstrip("*")] = digest
        for name in files:
            if name not in listed:
                add("error", "sha256sums_incomplete", f"SHA256SUMS 未列出 {name}")
            elif listed[name] != sha256_file(folder / name):
                add("error", "file_sha_mismatch", f"{name} 的哈希与 SHA256SUMS 不符（文件可能在发布后被改写）")
    r6 = folder / "r6_report.json"
    total = sum(len(v) for v in files.values())
    if not r6.exists():
        add("error", "r6_report_missing", "缺少 r6_report.json")
    else:
        rep = json.loads(r6.read_text("utf-8"))
        if rep.get("hard_hit_records", 1) != 0:
            add("error", "r6_hard_hits", f"隐私扫描硬命中 {rep.get('hard_hit_records')} 条")
        if rep.get("records") != total:
            add("warn", "r6_count_mismatch", f"隐私扫描覆盖 {rep.get('records')} 条，两份文件合计 {total} 条")
        if rep.get("file") and Path(rep["file"]).name not in files:
            add("info", "r6_file_label", f"r6_report 的 file 字段写的是 {Path(rep['file']).name}")
    ids = Counter(r.get("id") for rows in files.values() for r in rows)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        add("error", "duplicate_id", f"id 重复 {len(dup)} 个，如 {dup[:5]}")
    main = files.get(MAIN, [])
    hashes = Counter(r.get("doc_no_hash") for r in main if r.get("doc_no_hash"))
    dup_h = [h for h, n in hashes.items() if n > 1]
    if dup_h:
        add("warn", "duplicate_doc_no_hash", f"主文件内同一文号哈希出现多次 {len(dup_h)} 组（同一决定书多人时可能正常）")
    known = set(ids)
    dangling = sorted({link for rows in files.values() for r in rows for link in r.get("linked_ids") or []
                       if link not in known})
    if dangling:
        add("warn", "dangling_link", f"linked_ids 指向不存在的记录 {len(dangling)} 个")
    versions = Counter((r.get("schema_version"), r.get("pipeline_version")) for rows in files.values() for r in rows)
    if len(versions) > 1:
        add("error", "mixed_versions", f"一批里混有多个版本：{dict(versions)}")
    # 交付只带正文和处罚结果、不带要素值，本体的次版本变化（字段口径修订）不影响交付本身；主版本不同才退回
    major = SCHEMA_VERSION.split(".")[0]
    if any(str(v[0]).split(".")[0] != major for v in versions):
        add("error", "schema_version_mismatch", f"要素本体主版本应为 {major}.x，实为 {list(versions)}")
    elif any(v[0] != SCHEMA_VERSION for v in versions):
        add("info", "schema_minor_behind", f"交付标的本体版本 {sorted({v[0] for v in versions})}，现行 {SCHEMA_VERSION}；"
                                          "标注与抽取一律按现行版本")
    spread = []
    events = defaultdict(list)
    for r in main:
        d, _ = R.parse_date(r.get("behavior_date"))
        events[r.get("event_id")].append(d)
    for eid, ds in events.items():
        ds = [d for d in ds if d]
        if len(ds) > 1 and (max(ds) - min(ds)).days > EVENT_SPREAD_DAYS:
            spread.append(eid)
    if spread:
        add("warn", "event_date_spread", f"{len(spread)} 个事件内行为日期相差超过 {EVENT_SPREAD_DAYS} 天，如 {spread[:3]}")
    return out


def gate_stats(rows: list[dict]) -> dict:
    """在验收通过的主文件记录上算门禁相关的数量。"""
    n = len(rows)
    has_amount = sum(bool(((r.get("quality") or {}).get("completeness") or {}).get("has_amount")) for r in rows)
    severe = sum((r.get("outcome") or {}).get("detention_days", 0) >= 10 for r in rows)
    t_time = sum(1 for r in rows if (R.parse_date(r.get("behavior_date"))[0] or date.min) >= R.NEW_LAW_FROM)
    review_like = sum(r.get("source_type") in ("行政复议决定书", "行政判决书") for r in rows)
    outcome = Counter((r.get("outcome") or {}).get("type") for r in rows)
    stats = {
        "records": n,
        "events": len({r.get("event_id") for r in rows}),
        "by_province": dict(Counter(r.get("province") or r.get("region", "")[:2] for r in rows).most_common()),
        "by_source_type": dict(Counter(r.get("source_type") for r in rows)),
        "law_version": dict(Counter(r.get("law_version") for r in rows)),
        "outcome_type": dict(outcome),
        "completeness_has_amount": round(has_amount / n, 3) if n else 0,
        "t_time_behavior_2026": t_time,
        "tier_general": n - severe,
        "tier_severe": severe,
        "review_or_litigation_share": round(review_like / n, 3) if n else 0,
        "no_penalty": outcome.get("不予处罚", 0) + outcome.get("不构成违法", 0),
        # I-02：当事人段覆盖率（年龄、前科主要在这里）；打码罚款不能作罚款额目标
        "has_text_party": round(sum(bool(r.get(R.PARTY_SEGMENT)) for r in rows) / n, 3) if n else 0,
        "fine_masked": sum(bool((r.get("outcome") or {}).get("fine_masked")) for r in rows),
    }
    gaps = []
    if stats["completeness_has_amount"] < GATES["completeness"]:
        gaps.append(f"信息完整度 {stats['completeness_has_amount']:.0%} < {GATES['completeness']:.0%}（规格 §2）")
    if t_time < GATES["t_time"]:
        gaps.append(f"2026 年后行为 {t_time} 件 < {GATES['t_time']}（门禁 G1.1 T-time）")
    for name, k in (("一般档", "tier_general"), ("情节严重档（拘留 ≥10 日）", "tier_severe")):
        if stats[k] < GATES["tier_each"]:
            gaps.append(f"{name} {stats[k]} 件 < {GATES['tier_each']}（规格 §2）")
    if stats["no_penalty"] < 30:
        gaps.append(f"不予处罚、不构成违法 {stats['no_penalty']} 件，G3.2 要求单独达标")
    if n < GATES["gold_total"]:
        gaps.append(f"可进入标注的记录 {n} 件 < 金标目标 {GATES['gold_total']}（门禁 G1.1，尚需银标与人工校正）")
    stats["gaps"] = gaps
    return stats


def accept(folder: Path, out_root: Path | None = None) -> dict:
    files = {}
    parse_errors = {}
    for name in (MAIN, ONLY):
        if (folder / name).exists():
            files[name], parse_errors[name] = read_jsonl(folder / name)
    if MAIN not in files:
        raise SystemExit(f"{folder} 下没有 {MAIN}")
    per_file, rejected, accepted_main = {}, {}, []
    for name, rows in files.items():
        by_id = {}
        for r in rows:
            issues = R.check_delivery(r)
            if name == ONLY:  # 只有结果的条目不要求事实段相关项
                issues = [i for i in issues if i.code not in ("subject_not_in_facts", "conclusion_in_facts")]
            if issues:
                by_id[str(r.get("id"))] = issues
            errs = [i.code for i in issues if i.level == "error"]
            if errs:
                rejected[str(r.get("id"))] = (name, errs)
            elif name == MAIN:
                accepted_main.append(r)
        per_file[name] = {"records": len(rows), "bad_json": parse_errors[name],
                          "records_with_error": sum(1 for v in by_id.values() if any(i.level == "error" for i in v)),
                          "issues": R.summarize(by_id)}
    batch = batch_checks(folder, files)
    if any(b["level"] == "error" for b in batch) or any(parse_errors.values()):
        verdict = "不通过"
    elif rejected:
        verdict = "部分通过"
    else:
        verdict = "通过"
    main_sha = sha256_file(folder / MAIN)
    pipeline = (files[MAIN][0].get("pipeline_version") if files[MAIN] else "unknown") or "unknown"
    report = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "checker": CHECKER_VERSION,
        "delivery": str(folder), "main_sha256": main_sha, "pipeline_version": pipeline,
        "verdict": verdict, "batch_checks": batch, "files": per_file,
        "rejected": len(rejected), "accepted_main": len(accepted_main),
        "gate_stats_on_accepted": gate_stats(accepted_main),
    }
    out = (out_root or DATA / "engine" / "acceptance") / f"{pipeline}-{main_sha[:8]}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    with (out / "rejected.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "file", "error_codes"])
        for rid, (name, codes) in sorted(rejected.items()):
            w.writerow([rid, name, ";".join(sorted(set(codes)))])
    (out / "acceptance.md").write_text(render_md(report), "utf-8")
    report["out_dir"] = str(out)
    append_index(out.parent, report)
    return report


INDEX_COLUMNS = ["checked_at", "delivery_version", "main_sha256", "report_dir", "verdict", "rejected", "accepted_main",
                 "checker"]


def append_index(root: Path, rep: dict) -> None:
    """交付版本 → 报告目录的索引（引擎对 delivery/ 只读，不能把报告放进交付目录）。只追加。"""
    path = root / "INDEX.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(INDEX_COLUMNS)
        w.writerow([rep["checked_at"], Path(rep["delivery"]).name, rep["main_sha256"], Path(rep["out_dir"]).name,
                    rep["verdict"], rep["rejected"], rep["accepted_main"], rep["checker"]])


def render_md(rep: dict) -> str:
    g = rep["gate_stats_on_accepted"]
    lines = [f"# 交付验收报告：{rep['pipeline_version']}（{rep['main_sha256'][:8]}）", "",
             f"- 验收时间：{rep['checked_at']}，验收程序 {rep['checker']}",
             f"- 交付目录：`{rep['delivery']}`",
             f"- **结论：{rep['verdict']}**；退回 {rep['rejected']} 条，主文件可进入标注 {rep['accepted_main']} 条", "",
             "## 批次检查", ""]
    lines += [f"- {b['level']}｜{b['code']}：{b['message']}" for b in rep["batch_checks"]] or ["- 全部通过"]
    for name, f in rep["files"].items():
        lines += ["", f"## {name}（{f['records']} 条，含 error {f['records_with_error']} 条）", "",
                  "| 级别 | 问题 | 条数 | 说明 | 例 |", "|---|---|---|---|---|"]
        lines += [f"| {s['level']} | `{code}` | {s['count']} | {s['message'][:60]} | {', '.join(s['ids'][:3])} |"
                  for code, s in f["issues"].items()] or ["| — | 无 | 0 | | |"]
    lines += ["", "## 门禁相关数量（只计验收通过的主文件记录）", "",
              f"- 记录 {g['records']} 条、事件 {g['events']} 个；信息完整度 {g['completeness_has_amount']:.0%}",
              f"- 一般档 {g['tier_general']}、情节严重档 {g['tier_severe']}；2026 年后行为 {g['t_time_behavior_2026']} 件；"
              f"不予处罚与不构成违法 {g['no_penalty']} 件；复议与诉讼来源占 {g['review_or_litigation_share']:.0%}",
              f"- 地域：{', '.join(f'{k} {v}' for k, v in list(g['by_province'].items())[:8])}",
              f"- 法律版本：{g['law_version']}；处罚类型：{g['outcome_type']}",
              f"- 有当事人段 {g.get('has_text_party', 0):.0%}；罚款被源文打码 {g.get('fine_masked', 0)} 条（罚款额不作训练目标）",
              "", "> 自动验收通过只说明契约与隐私扫描规则满足，**不等于内容安全放行**；放行以金标线逐件复检为准。",
              "", "**门禁差距**：", ""]
    lines += [f"- {x}" for x in g["gaps"]] or ["- 无"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(DATA / "admin"))
    a = ap.parse_args(argv)
    rep = accept(Path(a.folder))
    print(Path(rep["out_dir"], "acceptance.md").read_text("utf-8"))
    print("报告目录：", rep["out_dir"])
    return 0 if rep["verdict"] != "不通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())

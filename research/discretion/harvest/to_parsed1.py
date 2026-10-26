"""网页解析产物 → 统一中间格式 parsed-1（L1，项目现状总览 §4–§5；契约 justilaw-api/app/discretion/records.py）。

parse.py 的内部形状（web_cases.pre_deid.jsonl）照旧保留；本模块把它转成三来源共用的 L1 格式，
写到 $JUSTILAW_DATA_DIR/parsed/web/<批次>/records.jsonl（+ stats.json），不覆盖已有批次。
构建脚本用 `build.py --parsed web=<该目录>` 读取，与法宝来源走同一条路径（I-13）。

字段要点：
  - source_ref = 原页 URL（解析层可以有，交付层不出现）；页面 id、站点、标题、发布单位等进 extra；
  - region / province 用站点→区划表（regions.csv），机关名留给构建兜底；
  - law_version 以所引法条为准（D8），未引用时按行为日，都没有写"未知"；
  - review：复议结论没解析出来的给空对象（解析层允许），交付构建会把它排除；
  - 段落必须是 text_full 的连续子串：字段式公示拼出来的决定段改取其中能原样找到的结果部分；
  - quality.tier：L1 金标候选 / L2 只有结果 / L3 范围外 / L4 待核（结果未解析）。

用法（仓库根目录）：python research/discretion/harvest/to_parsed1.py [--batch 名称]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "discover"))

from deid import doc_no_hash, find_subject  # noqa: E402
from regions import load_regions  # noqa: E402
from search import data_root  # noqa: E402

RECORD_VERSION = "parsed-1"
PARSER = "harvest/parse.py@0.7"
SEGMENTS = ("text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review")
REVIEW_VALUES = {"维持", "变更", "撤销", "确认违法", "程序驳回", "无"}
GAMBLING_FACT = re.compile(r"赌|抽头|抽水|六合彩|私彩|牌九|麻将|扑克|炸金花|押宝|牛牛|三公|推筒|跑胡子|下注|投注|彩票")
BOILERPLATE = re.compile(r"违法行为人|违法嫌疑人|被处罚人|因?实施了?|(?:为赌博提供条件、?)?赌博的?违法行为|的违法行为"
                         r"|于?\d{4}年\d{1,2}月(?:\d{1,2}日)?(?:[初中下上旬末底份]{0,2})?(?:至(?:\d{4}年)?\d{1,2}月(?:\d{1,2}日)?)?(?:间|期间)?"
                         r"|因赌博|参与赌博|进行赌博|[，,。、；\s]")
INTERNAL = ("page_id", "site", "title", "publisher", "item_index", "needs_ocr", "attachment_files",
            "raw_path", "html_table_index", "html_row_index")


def facts_sufficient(facts: str, decision: str = "", subject: str | None = None) -> bool:
    """数据收集计划 §4 纳入条件②：事实 ≥30 字、有赌博行为描述、不是结果表一行、去掉套话后仍有内容。"""
    f = facts or ""
    core = BOILERPLATE.sub("", f.replace(subject, "") if subject else f)
    return (len(re.sub(r"\s", "", f)) >= 30 and bool(GAMBLING_FACT.search(f)) and f != decision and len(core) >= 12)


def _segment(full: str, seg: str) -> str:
    """段落必须是正文的连续子串；拼接段（"依据；结果"）取能原样找到的结果部分。"""
    seg = (seg or "").strip()
    if not seg or seg in full:
        return seg
    parts = [p.strip() for p in re.split(r"[；;]", seg) if p.strip() and p.strip() in full]
    if not parts:
        return ""
    return next((p for p in parts if re.search(r"拘留|罚款|警告|不予|处罚", p)), max(parts, key=len))


def _event_key(c: dict, facts: str) -> str:
    d = re.search(r"\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?", facts or "")
    amt = re.search(r"(\d[\d,，.]*)\s*元", facts or "")
    if not (d or amt):
        return ""
    return "|".join((c.get("authority") or "", re.sub(r"\s", "", d.group(0)) if d else "", amt.group(1) if amt else ""))


def law_version(c: dict) -> str:
    arts = (c.get("outcome") or {}).get("articles") or []
    if not c.get("in_scope") and not any(re.search(r"治安管理处罚法第(七十|八十二)条", x) for x in arts):
        # 范围外、不按赌博条款处理的（禁毒、网络安全、卖淫嫖娼……）：契约的法定上限按赌博档次核，版本记"未知"免得误报
        return "未知"
    by_article = (c.get("outcome") or {}).get("law_version") or ""
    if by_article:
        return by_article
    bd = c.get("behavior_date") or ""
    if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", bd):
        return "新法" if bd >= "2026-01" else "旧法"
    return "未知"


def to_record(c: dict, regions: dict[str, dict], batch: str) -> dict:
    full = c.get("text_full") or ""
    segs = {s: _segment(full, c.get(s, "")) for s in SEGMENTS}
    offsets = {s: [full.find(v), full.find(v) + len(v)] for s, v in segs.items() if v}
    oc = dict(c.get("outcome") or {})
    extra_oc = {k: oc.pop(k) for k in ("detention_items", "from_execution_clause") if k in oc}
    lv = law_version(c)
    if oc.get("law_version"):
        oc["law_version"] = lv
    oc.setdefault("articles", [])
    oc.setdefault("detention_days", 0)
    oc.setdefault("fine", 0)
    oc.setdefault("detention_not_executed", "否")
    rv = dict(c.get("review") or {})
    rv = {"result": rv.get("result"), "changed_outcome": rv.get("changed_outcome") or None} \
        if rv.get("result") in REVIEW_VALUES else {}
    subject = find_subject(full) if c.get("in_scope") else None
    warns = list(c.get("parse_warnings") or [])
    if not c.get("in_scope"):
        tier = "L3-范围外"
    elif not oc.get("type"):
        tier = "L4-待核"
    elif facts_sufficient(segs["text_facts"], segs["text_decision"], subject):
        tier = "L1-金标候选"
    else:
        tier = "L2-只有结果"
    g = regions.get(c.get("site", ""), {})
    extra = {k: c[k] for k in INTERNAL if k in c}
    if extra_oc:
        extra["outcome"] = extra_oc
    if g.get("province_code"):
        extra.update({"province_code": g["province_code"], "region_level": g.get("level", "")})
    rec = {
        "record_version": RECORD_VERSION, "id": c["id"], "source": "公开网页", "batch": batch, "parser": PARSER,
        "source_type": c.get("source_type") or "处罚决定书", "source_ref": c.get("source_ref", ""),
        "doc_no": c.get("doc_no", ""), "doc_no_hash": doc_no_hash(c["doc_no"]) if c.get("doc_no") else "",
        "harvest_date": c.get("harvest_date", ""), "deidentified": False,
        "behavior_date": c.get("behavior_date", ""), "decision_date": c.get("decision_date", ""),
        "authority": c.get("authority", ""), "region": g.get("region_code", ""), "province": g.get("province", ""),
        "law_version": lv, "subject_mention": subject or "", "event_key": _event_key(c, segs["text_facts"]),
        "text_full": full, "segmented": bool(c.get("segmented")), "segments": offsets, **segs,
        "outcome": oc, "review": rv,
        "quality": {"tier": tier, "in_scope": bool(c.get("in_scope")), "form": c.get("source_type", ""),
                    "gambling": c.get("gambling") or "待定", "ocr": bool(c.get("ocr")),
                    "completeness": c.get("completeness") or {"has_amount": False, "has_outcome": False},
                    "parse_warnings": warns, "facts_contains_conclusion": "facts_contains_conclusion" in warns},
        "extra": extra,
    }
    return rec


def new_batch_dir(base: Path, name: str) -> Path:
    """L1 只追加新批次、不覆盖：同名已存在时加 -r2、-r3……"""
    d, k = base / name, 2
    while d.exists():
        d, k = base / f"{name}-r{k}", k + 1
    return d


def repair_table_batch(source: Path, out: Path, regions: dict[str, dict]) -> dict:
    """Append-only parsed-1 rebuild: replace only pages with explicit HTML case rows."""
    from parse import html_table_cases  # noqa: PLC0415

    if out.exists():
        raise FileExistsError(out)
    old = [json.loads(line) for line in source.open(encoding="utf-8") if line.strip()]
    pages = {}
    manifest = data_root().parent / "harvest" / "pages.jsonl"
    for row in (json.loads(line) for line in manifest.open(encoding="utf-8") if line.strip()):
        if row.get("status") == "ok" and row.get("url"):
            pages[row["url"]] = row
    replacements = {}
    for url, page in pages.items():
        cases = html_table_cases(page)
        if cases:
            replacements[url] = [to_record(case, regions, out.name) for case in cases]
    removed = [row["id"] for row in old if row.get("source_ref") in replacements]
    kept = [{**row, "batch": out.name} for row in old if row.get("source_ref") not in replacements]
    repaired = [row for url in sorted(replacements) for row in replacements[url]]
    records = kept + repaired
    if len({row["id"] for row in records}) != len(records):
        raise ValueError("duplicate record ID after table repair")
    out.mkdir(parents=True)
    with (out / "records.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats = {"record_version": RECORD_VERSION, "parser": PARSER, "batch": out.name,
             "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
             "records": len(records), "unchanged_records": len(kept),
             "table_pages": len(replacements), "old_table_records_removed": len(removed),
             "table_records_added": len(repaired),
             "tier": dict(Counter(row["quality"]["tier"] for row in records))}
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "replacement-manifest.json").write_text(
        json.dumps({"source_sha256": stats["source_sha256"], "removed_ids": removed,
                    "added_ids": [row["id"] for row in repaired],
                    "source_urls": sorted(replacements)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="网页解析产物 → parsed-1")
    ap.add_argument("--src", default="", help="缺省 $DATA/admin/web_cases.pre_deid.jsonl")
    ap.add_argument("--batch", default="", help="批次名，缺省 YYYYMMDD-web")
    ap.add_argument("--repair-table-from", default="", help="已有 parsed-1 records.jsonl；只重建原 HTML 多列表格页")
    args = ap.parse_args()
    root = data_root().parent
    if args.repair_table_from:
        name = args.batch or date.today().strftime("%Y%m%d") + "-table-repair"
        out = root / "parsed" / "web" / name
        stats = repair_table_batch(Path(args.repair_table_from), out, load_regions())
        print(json.dumps(stats, ensure_ascii=False, indent=1), "→", out)
        return 0
    src = Path(args.src) if args.src else root / "admin" / "web_cases.pre_deid.jsonl"
    cases = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    regions = load_regions()
    name = args.batch or date.today().strftime("%Y%m%d") + "-web"
    out = new_batch_dir(root / "parsed" / "web", name)
    # 只有附件、还没 OCR 出正文的占位页不进 L1（text_full 为空，契约不允许）
    recs = [to_record(c, regions, out.name) for c in cases if (c.get("text_full") or "").strip()]
    out.mkdir(parents=True)
    with open(out / "records.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    stats = {"record_version": RECORD_VERSION, "parser": PARSER, "batch": out.name, "source": str(src),
             "records": len(recs), "tier": dict(Counter(r["quality"]["tier"] for r in recs)),
             "in_scope_without_region": sum(r["quality"]["in_scope"] and not r["region"] for r in recs)}
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        sys.path.insert(0, str(HERE.parent / "collect"))
        from common import registry_add  # noqa: PLC0415
        registry_add("L1", out, records=len(recs), producer="harvest/to_parsed1.py", pipeline_version=PARSER,
                     note=f"网页 parsed-1，来自 {src.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 登记表写入失败（忽略）：{exc}")
    print(json.dumps(stats, ensure_ascii=False, indent=1), "→", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

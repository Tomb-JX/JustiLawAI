"""作业单（jobs）：把 MCP 检索结果或清洗候选清单变成可执行的下载任务。

两种来源（设计 §10.4）：
  from-mcp  读调用层缓存（$DATA/engine/pkulaw_mcp/cache/pkulaw-enforcement-doc_mcp/*.json，
            每行含 url 直达详情页）——同参数缓存免费，0 积分；
  from-csv  读清洗候选清单（含「原文链接」列，如 worklist-清洗版-2026.csv）。

输出 jobs.jsonl（每行一件）+ jobs.meta.json（计数、过滤条件、输入哈希，供 run 报告引用）。
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

LAW_NEW_MARKS = ("2025修订", "第82条", "第八十二条")


def parse_year(date_str: str) -> str:
    import re
    m = re.search(r"(20\d{2})", date_str or "")
    return m.group(1) if m else ""


def law_is_new(according_law) -> bool:
    if isinstance(according_law, (list, tuple)):
        s = " ".join(str(x) for x in according_law)
    else:
        s = str(according_law or "")
    return any(m in s for m in LAW_NEW_MARKS)


def row_to_job(row: dict, *, source: str, source_query: str = "") -> dict | None:
    """MCP 行 / CSV 行 → 作业。缺文号且缺链接的丢弃。"""
    url = str(row.get("url") or "").strip()
    doc_no = str(row.get("documentNo") or row.get("doc_no") or "").strip()
    if not url and not doc_no:
        return None
    law_raw = row.get("accordingLaw") or row.get("according_law") or ""
    return {
        "doc_no": doc_no,
        "url": url,
        "title": str(row.get("title") or ""),
        "organ": str(row.get("punishOrgan") or row.get("organ") or ""),
        "punishment_date": str(row.get("punishmentDate") or row.get("punishment_date") or ""),
        "according_law": law_raw if isinstance(law_raw, list) else [law_raw] if law_raw else [],
        "law": "新法" if law_is_new(law_raw) else "",
        "source": source,
        "source_query": source_query,
    }


def load_mcp_rows(cache_dir: Path) -> list[tuple[dict, str, str]]:
    """读调用层缓存目录 → [(行, 检索词, fetched_at)]。非 search_enforcement 的结构跳过。"""
    out: list[tuple[dict, str, str]] = []
    for f in sorted(Path(cache_dir).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        st = d.get("structured") or {}
        data = st.get("data") if isinstance(st, dict) else None
        if not isinstance(data, list):
            continue
        q = str((d.get("arguments") or {}).get("queryText") or "")
        fetched = str(d.get("fetched_at") or "")
        for r in data:
            if isinstance(r, dict):
                out.append((r, q, fetched))
    return out


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _write(out: Path, jobs: list[dict], meta: dict) -> dict:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    meta.update({"jobs": len(jobs), "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "out": str(out)})
    (out.parent / (out.stem + ".meta.json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def jobs_from_mcp(cache_dir: Path, *, out: Path, year: str = "", law: str = "",
                  organ: str = "") -> dict:
    rows = load_mcp_rows(Path(cache_dir))
    seen: set[str] = set()
    jobs: list[dict] = []
    no_url = 0
    for r, q, _fetched in rows:
        j = row_to_job(r, source="mcp", source_query=q)
        if j is None or not j["url"]:  # 没有链接的条目无法执行，不进作业单
            no_url += 1
            continue
        key = j["doc_no"] or j["url"]
        if key in seen:
            continue
        if year and parse_year(j["punishment_date"]) != year:
            continue
        if law == "新法" and j["law"] != "新法":
            continue
        if organ and organ not in j["organ"]:
            continue
        seen.add(key)
        jobs.append(j)
    filters = {"year": year, "law": law, "organ": organ}
    return _write(out, jobs, {"source": "mcp-cache", "cache_dir": str(cache_dir),
                              "cache_rows": len(rows), "skipped_no_url": no_url,
                              "filters": filters})


CSV_COLS = {"doc_no": "发文案号", "title": "标题", "organ": "处罚机关",
            "punishment_date": "公布日期", "according_law": "依据法条",
            "url": "原文链接"}


def jobs_from_csv(csv_path: Path, *, out: Path, year: str = "") -> dict:
    csv_path = Path(csv_path)
    jobs: list[dict] = []
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            row = {k: raw.get(v, "") for k, v in CSV_COLS.items()}
            j = row_to_job(row, source="csv")
            if j is None or not j["url"]:
                continue
            if year and parse_year(j["punishment_date"]) != year:
                continue
            key = j["doc_no"] or j["url"]
            if key in seen:
                continue
            seen.add(key)
            jobs.append(j)
    return _write(out, jobs, {"source": "csv", "csv": str(csv_path),
                              "csv_sha256": _sha256_file(csv_path),
                              "filters": {"year": year}})

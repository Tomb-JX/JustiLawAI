"""检索执行（M2）：作业单 → 分页检索 → results.jsonl，饱和自动拆分。

设计（docs/04-plan/pkulaw-agent-design.md §4–5）：
- 普通检索走已实测的 API 端点族 `POST /searchingapi/adv/list/{lib}`；
- 作业单（plan）里可以给"简化节点"（text/select/group_by，形态沿用存量项目跑通的 pfnl 结构），
  也可以给 `field_nodes` **原样节点**（recon 捕获到什么就用什么，绝不臆造 schema）；
- 每页请求体原样落 `run.json`，首轮联测后据此对齐真实字段；
- 结果项字段名未知，用候选名单取值（gid/title/url/date/docNo/region），并保留 raw。

纯函数（expand_runs/build_* / item_*/split_plan）可单测；网络部分只用 PkulawApi。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from pkulaw_agent.api import PAGE_SIZE_DEFAULT, PkulawApi, build_search_body

TEXT_NODE_FIELDS = ("FullText", "Title", "DocumentNo")  # 已知家族里 text 型字段的候选


# ---------------- 作业单 ----------------
def plan_template() -> dict:
    """plan.json 模板（写进 --template 输出，agent/用户按此填）。"""
    return {
        "batch": "js-2022H1",
        "lib": "apy",
        "runs": [
            {
                "id": "js-2022-抽头",
                "terms": ["抽头"],
                "region": "江苏省",
                "window": ["2022-01-01", "2022-12-31"],
            }
        ],
        "search": {"page_size": 50, "max_pages": 40, "limit": 500, "order_by": ""},
        "split": {"field": "PublishDate", "mode": "group_by",
                  "values": ["2022", "2021", "2020"]},
        "fetch": {"only": "narrative", "min_interval_s": 2.0},
    }


def load_plan(path: Path) -> dict:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if not plan.get("lib"):
        raise ValueError("plan 缺 lib（apy=行政执法 / pfnl=司法案例 / chl=法规）")
    if not plan.get("runs"):
        raise ValueError("plan 缺 runs（至少一个检索任务）")
    return plan


def expand_runs(plan: dict) -> list[dict]:
    """runs 里 terms × windows 展开成最小检索单元；region/window 可省。"""
    out: list[dict] = []
    lib = plan["lib"]
    for run in plan["runs"]:
        terms = run.get("terms") or ([run["term"]] if run.get("term") else [])
        if not terms:
            raise ValueError(f"run 缺 terms：{run}")
        windows = run.get("windows") or ([run["window"]] if run.get("window") else [[]])
        for term in terms:
            for window in windows:
                parts = [run.get("id") or term]
                if len(terms) > 1:
                    parts.append(term)
                if len(windows) > 1 and window:
                    parts.append(window[0][:7])
                out.append({
                    "id": "-".join(parts), "lib": lib, "term": term,
                    "region": run.get("region", ""), "window": list(window),
                    "field_nodes": run.get("field_nodes"),
                    "group_by": run.get("group_by"),
                    "extra_filters": run.get("extra_filters"),
                })
    return out


# ---------------- 请求体构造（已知家族结构 + 原样节点） ----------------
def text_node(field_name: str, value: str) -> dict:
    """text 型检索节点（结构与存量项目跑通的 pfnl 节点一致）。"""
    return {
        "type": "text", "order": 0, "combineAs": 2, "fieldName": field_name,
        "showText": field_name, "subCombineAs": 2,
        "fieldItems": [{
            "values": value, "valuesCombineAs": 2,
            "extra": {"values": "", "combineAs": 2},
            "matchType": 1, "matchSpan": 1, "matchSpanGap": 0,
            "fieldScope": {"fieldName": "", "showText": ""},
            "order": 0, "filterNodes": [],
        }],
        "matchTypeEnabled": False, "matchSpanEnabled": True, "matchSpans": None,
    }


def select_node(field_name: str, values: list[str], items: list[dict] | None = None) -> dict:
    """select 型节点；items 可给 [{"text","path","name","value"}]，缺省用 values 生成。"""
    if items is None:
        items = [{"text": v, "path": v, "name": v, "value": v} for v in values]
    return {
        "type": "select", "order": 0, "combineAs": 2, "fieldName": field_name,
        "showText": field_name,
        "fieldItems": [{"items": items, "combineAs": 2, "order": 0, "filterNodes": []}],
    }


def build_body_from_run(run: dict, plan: dict, *, page_index: int = 0,
                        page_size: int = PAGE_SIZE_DEFAULT,
                        order_by: str = "", group_by: dict | None = None) -> dict:
    """按 run 组装请求体：原样 field_nodes 优先；否则用简化节点（关键词 + 地域 + 时间窗）。

    简化节点使用的字段名来自作业单 `field_names`（缺省用已知家族候选）；未知字段名不臆造。
    """
    if run.get("field_nodes"):
        nodes = run["field_nodes"]
    else:
        names = plan.get("field_names", {})
        nodes = [text_node(names.get("full_text", "FullText"), run["term"])]
        if run.get("region"):
            nodes.append(text_node(names.get("region", "Regional"), run["region"]))
        if run.get("extra_filters"):
            nodes.extend(run["extra_filters"])
    gb = group_by if group_by is not None else (run.get("group_by") or {})
    body = build_search_body(page_index=page_index, page_size=page_size,
                             order_by=order_by, field_nodes=nodes, group_by=gb)
    if run.get("window") and plan.get("date_filter"):
        df = plan["date_filter"]  # {"field": "...", "style": "field_node|extra"}
        body.setdefault("dateFilters", []).append(
            {"fieldName": df.get("field", ""), "start": run["window"][0],
             "end": run["window"][1], "style": df.get("style", "field_node")})
    return body


# ---------------- 结果项归一化（字段名未知 → 候选取值 + 保留 raw） ----------------
def item_pick(item: dict, *names: str) -> str:
    for n in names:
        v = item.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and v:
            return str(v)
    return ""


def normalize_item(item: dict, lib: str) -> dict:
    gid = item_pick(item, "gid", "Gid", "id", "Id", "recordId", "RecordId",
                    "pklawId", "docId", "identifier")
    url = item_pick(item, "url", "Url", "link", "Link", "docUrl", "htmlUrl", "fullTextLink")
    if not url and gid:
        url = f"/{lib}/{gid}.html"
    return {
        "gid": gid,
        "title": item_pick(item, "title", "Title", "name", "Name", "docTitle"),
        "doc_no": item_pick(item, "documentNo", "DocumentNo", "docNo", "caseFlag", "no"),
        "date": item_pick(item, "issueDate", "IssueDate", "publishDate", "PublishDate",
                          "punishDate", "date", "Date", "lastInstanceDate"),
        "region": item_pick(item, "lawRegional", "regional", "region", "province", "area"),
        "authority": item_pick(item, "lawEnforceType", "authority", "organ", "department"),
        "url": url,
        "raw": item,
    }


def item_key(norm: dict) -> str:
    return norm["gid"] or norm["url"] or norm["doc_no"] or norm["title"]


# ---------------- 执行 ----------------
def run_search(api: PkulawApi, plan: dict, run: dict, out_dir: Path,
               *, page_size: int = PAGE_SIZE_DEFAULT, max_pages: int = 40,
               limit: int = 500, order_by: str = "", split: dict | None = None,
               dump_bodies: bool = False, logger=print) -> dict:
    """执行一个检索单元；命中超过 max_pages*page_size 且有 split 配置时按 split.values 拆分。

    产出：out_dir/results.jsonl（去重后结果）、out_dir/run.json（条件/计数/请求体样本）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    seen: set[str] = set()
    rows: list[dict] = []
    pages: list[dict] = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    total = None

    def _crawl(group_by: dict | None, tag: str) -> int:
        nonlocal total
        got = 0
        for page_index in range(max_pages):
            body = build_body_from_run(run, plan, page_index=page_index,
                                       page_size=page_size, order_by=order_by,
                                       group_by=group_by)
            if dump_bodies and page_index == 0:
                logger(f"[body]{tag} {json.dumps(body, ensure_ascii=False)}")
            data = api.search(run["lib"], body)
            items = data.get("data") or data.get("list") or data.get("rows") or []
            if total is None:
                total = int(data.get("total") or data.get("Total") or 0)
            pages.append({"tag": tag, "pageIndex": page_index, "items": len(items),
                          "total": data.get("total")})
            if not items:
                break
            for item in items:
                norm = normalize_item(item, run["lib"])
                key = item_key(norm)
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append(norm)
                got += 1
                if len(rows) >= limit:
                    logger(f"  达到上限 {limit}，停止")
                    return got
        return got

    if split and split.get("values"):
        for value in split["values"]:
            if len(rows) >= limit:
                break
            tag = f"{split.get('field','')}={value}"
            group = {split["field"]: str(value)} if split.get("mode", "group_by") == "group_by" else {}
            sub_run = dict(run)
            if split.get("mode") == "field_node":
                sub_run["extra_filters"] = (run.get("extra_filters") or []) + [
                    text_node(split["field"], str(value))]
            logger(f"  拆分：{tag}")
            got = _crawl(group or None, tag)
            logger(f"    {tag} 新增 {got}（累计 {len(rows)}）")
    else:
        _crawl(None, "all")
        if total and total > page_size * max_pages and split:
            logger(f"  命中 {total} 超过单任务上限 {page_size * max_pages}，"
                   f"但 split 无 values —— 请补 split.values（如按年份），否则会截断")

    with results_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {
        "run_id": run["id"], "lib": run["lib"], "term": run["term"],
        "region": run.get("region", ""), "window": run.get("window", []),
        "started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_reported": total, "unique": len(rows), "pages": pages,
        "results": str(results_path),
    }
    (out_dir / "run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger(f"✓ {run['id']}: 命中总数 {total}，去重后 {len(rows)} → {results_path}")
    return summary


def iter_results(run_dir: Path) -> Iterable[dict]:
    for line in (Path(run_dir) / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)

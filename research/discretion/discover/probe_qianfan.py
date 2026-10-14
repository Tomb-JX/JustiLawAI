"""发现层 M0 探针：验证百度千帆「百度搜索」API 在本项目检索场景下的实际行为。

设计文档：docs/04-plan/search-discovery-design.md §3、§9（M0）。
文档没写清、必须实测才能定方案的 6 个问题（每个 1 次调用，共 6 次，免费额度内）：
  T1 基线：不加任何过滤，top_k=50 能返回多少条、gov.cn 占比、标题像赌博文书的占比
  T2 query 里写 site:gov.cn 是否生效
  T3 search_filter.match.site=["gov.cn"] 是否按后缀匹配所有 *.gov.cn 子域
  T4 site 列表指定两个县级域名时，结果是否只来自这两个域名
  T5 page_time 区间过滤（2026 年）是否生效
  T6 关闭 query 改写（enable_rewrite=false）对精确检索式的影响
第二轮（4 次调用）：
  T7/T8 时间过滤的正确写法（日期表达式 now-1y/d、recency 枚举 year）
  T9/T10 query 内 site: 能否限定到单个县级域名（含 zwfw. 等子域），用于逐县枚举

用法（仓库根目录）：
  设置环境变量 QIANFAN_API_KEY（百度智能云控制台创建的 API Key，不要写进任何文件）
  python research/discretion/discover/probe_qianfan.py            # 全部测试
  python research/discretion/discover/probe_qianfan.py T7 T8 T9 T10   # 只跑指定测试
产出：$JUSTILAW_DATA_DIR/discover/probe/<时间戳>/ 下每个测试的原始响应 JSON + summary.md
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

API = "https://qianfan.baidubce.com/v2/ai_search/web_search"
DATA_DIR = Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research"))
BASE_Q = "行政复议决定书 赌博 治安管理处罚法第七十条"
GAMBLING_TITLE = re.compile(r"赌|复议决定|行罚决字|处罚决定")

TESTS: list[tuple[str, str, dict]] = [
    ("T1_baseline", BASE_Q, {}),
    ("T2_inline_site", BASE_Q + " site:gov.cn", {}),
    ("T3_filter_suffix", BASE_Q, {"search_filter": {"match": {"site": ["gov.cn"]}}}),
    ("T4_filter_domains", "行政复议决定书 赌博", {"search_filter": {"match": {"site": ["www.zjwy.gov.cn", "www.huadu.gov.cn"]}}}),
    ("T5_page_time_2026", "赌博 行政处罚决定书 第八十二条", {"search_filter": {"range": {"page_time": {"gte": "2026-01-01", "lte": "now/d"}}}}),
    ("T6_no_rewrite", BASE_Q, {"query_policy": {"enable_rewrite": False}}),
    # 第二轮（M0 首轮结果见设计 §2.1）：T5 的绝对日期报 Invalid time range option，补测官方示例的日期表达式与 recency 枚举；
    # T3 表明 match.site 不认后缀，补测 query 内 site: 能否限定到单个县级域名（含子域）
    ("T7_page_time_math", "赌博 行政处罚决定书 第八十二条 site:gov.cn", {"search_filter": {"range": {"page_time": {"gte": "now-1y/d", "lte": "now/d"}}}}),
    ("T8_recency_year", "赌博 行政处罚决定书 第八十二条 site:gov.cn", {"search_recency_filter": "year"}),
    ("T9_inline_county", "赌博 site:dingxing.gov.cn", {}),
    ("T10_inline_county_doc", "行罚决字 赌博 site:dingxing.gov.cn", {}),
]


def call(key: str, query: str, extra: dict) -> dict:
    body = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": 50}],
        **extra,
    }
    s = requests.Session()
    s.trust_env = False
    r = s.post(API, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    return {"status": r.status_code, "request": body, "response": r.json() if r.content else {}}


def summarize(name: str, res: dict) -> str:
    refs = (res["response"] or {}).get("references") or []
    hosts = [urlparse(x.get("url", "")).hostname or "" for x in refs]
    gov = sum(h.endswith("gov.cn") for h in hosts)
    hit = sum(bool(GAMBLING_TITLE.search(x.get("title", ""))) for x in refs)
    dates = sorted(x.get("date") or "" for x in refs if x.get("date"))
    err = (res["response"] or {}).get("message") or (res["response"] or {}).get("code") or ""
    span = f"{dates[0][:10]}～{dates[-1][:10]}" if dates else "-"
    top_hosts = ", ".join(sorted(set(hosts))[:6])
    return f"| {name} | {res['status']} | {len(refs)} | {gov} | {hit} | {span} | {top_hosts} | {err} |"


def main() -> None:
    key = os.environ.get("QIANFAN_API_KEY")
    if not key:
        sys.exit("缺少环境变量 QIANFAN_API_KEY（百度智能云千帆控制台 → API Key）。本脚本不读取任何文件里的密钥。")
    out = DATA_DIR / "discover" / "probe" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    rows = [
        "| 测试 | HTTP | 返回条数 | gov.cn 条数 | 标题像目标文书 | 日期范围 | 域名样例 | 错误 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    only = {a for a in sys.argv[1:] if a.startswith("T")}  # 例：python probe_qianfan.py T7 T8 只跑这两项
    for name, q, extra in TESTS:
        if only and name.split("_")[0] not in only:
            continue
        res = call(key, q, extra)
        (out / f"{name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append(summarize(name, res))
        print(rows[-1], flush=True)
        time.sleep(1.5)
    (out / "summary.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n原始响应与汇总 → {out}")


if __name__ == "__main__":
    main()

"""司法案例库覆盖普查：为"行政案例金标从哪来"提供定量依据。

对照对象是本项目 2026-10-15/16 在**裁判文书网**做的检索实验（见 docs/05-research/gambling-documents-and-retrieval.md §4.2）：
  刑事 案由赌博罪 52,218 / 开设赌场罪 141,804；行政 全文"赌博" 3,971（判决书 2,367）、全文"参与赌博" 1,024。
本脚本回答：同样口径在**法宝司法案例库**里有多少、更新到哪一年、能不能替代采购。

每条查询 25 分（case-keyword），结果按参数缓存（同参数重跑 0 分）；全部记入共用台账。
用法（仓库根目录）：
  python research/eval/pkulaw_mcp/probe_cases.py --workstream data --budget 300
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pkulaw_mcp.client import Gateway  # noqa: E402

QUERIES: list[tuple[str, dict]] = [
    # 参数名必须是网关的原始名（caseClassName / documentAttr / startLastInstanceDate…），
    # 用服务封装的别名（case_class）直连 gw.call 会被网关忽略、过滤失效（踩过：返回全类型 103 万条）。
    ("行政一审 全文赌博", dict(fulltext="赌博", caseClassName="行政一审")),
    ("行政一审 全文参与赌博", dict(fulltext="参与赌博", caseClassName="行政一审")),
    ("行政二审 全文赌博", dict(fulltext="赌博", caseClassName="行政二审")),
    ("行政一审 全文赌博 仅判决书", dict(fulltext="赌博", caseClassName="行政一审", documentAttr=["判决书"])),
    ("行政一审 全文赌博 2026 年审结", dict(fulltext="赌博", caseClassName="行政一审",
                                        startLastInstanceDate="2026.01.01", endLastInstanceDate="2026.12.31")),
    ("行政一审 全文赌博 2025 年审结", dict(fulltext="赌博", caseClassName="行政一审",
                                        startLastInstanceDate="2025.01.01", endLastInstanceDate="2025.12.31")),
    ("行政一审 全文赌博 裁定书", dict(fulltext="赌博", caseClassName="行政一审", documentAttr=["裁定书"])),
    ("刑事一审 标题赌博罪", dict(title="赌博罪", caseClassName="刑事一审")),
    ("刑事一审 标题开设赌场罪", dict(title="开设赌场罪", caseClassName="刑事一审")),
    ("行政一审 全文赌博不予处罚", dict(fulltext="赌博 不予处罚", caseClassName="行政一审")),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workstream", default="data")
    ap.add_argument("--budget", type=int, default=300)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    gw = Gateway(budget=args.budget, workstream=args.workstream)
    out: dict = {"surveyed_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "queries": []}
    print(f"{'查询':<28} {'命中总数':>8}  样本（标题 / 法院 / 审结日期）")
    for label, params in QUERIES:
        r = gw.call("/mcp-case", "get_case_list", params, points=25, refresh=args.refresh)
        d = (r.get("structured") or {})
        total = d.get("Total")
        data = d.get("Data") or []
        samples = [
            f"{(x.get('Title') or '')[:26]}｜{(x.get('Court') or '')[:12]}｜{x.get('LastInstanceDate') or ''}"
            for x in data[:3]
        ]
        flag = "（缓存）" if r.get("cached") else ""
        print(f"{label:<28} {str(total):>8}  {flag}")
        for s in samples:
            print(f"{'':<30}{s}")
        out["queries"].append({"label": label, "params": params, "total": total,
                               "returned": len(data), "samples": samples,
                               "categories": sorted({c for x in data[:20] for c in (x.get("Category") or [])})})
    out["spent_points"] = gw.spent
    dest = gw.data_dir / "case_survey.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n本次花费 {gw.spent} 分 → {dest}")


if __name__ == "__main__":
    main()

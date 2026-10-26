"""P9 收割驱动：行政执法库 keyword 模式 × 分省 × 锚族 × 年代切片，走引擎 Gateway（缓存+台账+预算闸门）。

方法论（2026-10-26 实测定案，playbook §20）：
- onsite 锚族（缴获赌资/现场查获赌资…）在**语义模式**只对江浙鲁生效，对华中/华南新省全部 0 召回；
  **关键词模式**（token-AND）跨省生效且召回即高质量（处罚种类含没收+治安法70条）。
- 每次调用最多 50 条、可翻页；本驱动用**年代切片**做确定性深采（不依赖游标链，可重放/可缓存）。
- 河南省剔除：keyword+lawRegional 出现归属错配（返回广西/江苏件），不可锚定。

用法：
    python -m pkulaw_agent.harvest_mcp --plan          # 只列 cells 与预算，不花钱
    python -m pkulaw_agent.harvest_mcp --execute       # 跑波（budget 封顶内置）
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "eval"))  # research/eval
from pkulaw_mcp.client import Gateway

PROVS = ["湖北省", "湖南省", "四川省", "江西省", "河北省", "广东省", "福建省", "安徽省"]
ANCHORS = ["赌资 拘留", "收缴赌资", "赌资 罚款", "开设赌场"]
SLICES = [("2013.01.01", "2020.12.31"), ("2021.01.01", "2026.10.26")]
POINTS_PER_CALL = 75
TOTAL_BUDGET = 4_800  # 64 次封顶；剩余分留给二波


def cells() -> list[dict]:
    out = []
    for prov in PROVS:
        for anchor in ANCHORS:
            for start, end in SLICES:
                out.append({"queryText": anchor, "lawRegional": [prov], "searchType": "keyword",
                            "pageSize": 50, "startPunishmentDate": start, "endPunishmentDate": end})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    cs = cells()
    need = len(cs) * POINTS_PER_CALL
    print(f"cells: {len(cs)}（{len(PROVS)} 省 × {len(ANCHORS)} 锚 × {len(SLICES)} 年代片）预计 {need} 分")
    if args.plan:
        for c in cs[:6]:
            print("  例:", c)
        return 0
    if not args.execute:
        return 0
    if need > TOTAL_BUDGET:
        print(f"超预算闸门 {TOTAL_BUDGET}，停"); return 1

    gw = Gateway(workstream="data")
    bal = gw.call("/pkulaw-account/mcp", "get_points_balance", {}, points=0, refresh=True)["structured"]
    print(f"起算余额: {bal.get('availablePoints')}")

    ok = fail = 0
    for i, c in enumerate(cs, 1):
        try:
            r = gw.call("/pkulaw-enforcement-doc/mcp", "search_enforcement", c, points=75)
            st = r.get("structured") or {}
            n = st.get("total")
            got = len(st.get("data") or [])
            ok += 1
            print(f"[{i:02d}/{len(cs)}] {c['lawRegional'][0]} {c['queryText']}@{c['startPunishmentDate'][:4]}… "
                  f"total={n} page={got} cached={r.get('cached')}")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"[{i:02d}] ✗ {c['lawRegional'][0]} {c['queryText']}: {str(exc)[:80]}")
            if "积分" in str(exc) or "余额" in str(exc) or "Insufficient" in str(exc):
                print("积分不足，硬停"); break
        time.sleep(1.2)
    print(f"✓ 完成 ok={ok} fail={fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

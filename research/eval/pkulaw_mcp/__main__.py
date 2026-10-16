"""命令行入口（在 research/eval 目录下运行 `python -m pkulaw_mcp ...`，或直接运行本文件）。

  balance                         积分余额与即将过期（0 分）
  services [--refresh]            服务清单与单价；--refresh 对照账户实时单价（0 分）
  tools <服务>                    该服务的工具与参数（tools/list，0 分）
  call <服务> <工具> '<json>'     调用；必须给 --budget（本次最多花多少分）
  ledger                          台账汇总：按工作流、服务统计花费
  seed <服务> <工具> '<json>' <原始响应文件>   把已付费的原始响应写入缓存
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pkulaw_mcp"

from pkulaw_mcp.client import Gateway  # noqa: E402
from pkulaw_mcp.services import SERVICES, Pkulaw  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="pkulaw_mcp")
    ap.add_argument("--workstream", default="engine", help="记入台账的工作流名（engine / data）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("balance")
    p = sub.add_parser("services")
    p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("tools")
    p.add_argument("service")
    p = sub.add_parser("call")
    p.add_argument("service")
    p.add_argument("tool")
    p.add_argument("arguments")
    p.add_argument("--budget", type=int, required=True)
    p.add_argument("--refresh", action="store_true", help="忽略缓存重新付费调用")
    sub.add_parser("ledger")
    p = sub.add_parser("seed")
    p.add_argument("service")
    p.add_argument("tool")
    p.add_argument("arguments")
    p.add_argument("response_file")
    a = ap.parse_args(argv)

    if a.cmd == "ledger":
        gw = Gateway()
        if not gw.ledger_path.exists():
            print("台账为空")
            return 0
        spent = defaultdict(int)
        calls = defaultdict(int)
        hits = 0
        with gw.ledger_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                spent[(row["workstream"], row["service"])] += int(row["points"])
                calls[(row["workstream"], row["service"])] += 1
                hits += int(row["cache_hit"])
        for k in sorted(spent):
            print(f"{k[0]:<8} {k[1]:<34} 调用 {calls[k]:>4} 次，花 {spent[k]:>6} 分")
        print(f"合计 {sum(spent.values())} 分；缓存命中 {hits} 次")
        return 0

    gw = Gateway(budget=getattr(a, "budget", None), workstream=a.workstream)
    pk = Pkulaw(gw)
    if a.cmd == "balance":
        print(json.dumps(pk.balance(365), ensure_ascii=False, indent=1))
    elif a.cmd == "services":
        live = {}
        if a.refresh:
            live = {i["serverId"]: i for i in pk.entitlements().get("items", [])}
        for s in SERVICES.values():
            note = ""
            if live:
                match = live.get(s.path.strip("/").split("/")[0])  # serverId = 路径第一段
                note = "（未开通）" if not match or not match.get("turnedOn") else (
                    "" if match["pointsPerCall"] == s.points else f"（单价已变为 {match['pointsPerCall']}）")
            print(f"{s.id:<20} {s.points:>4} 分  {s.title:<12} {s.use}{note}")
    elif a.cmd == "tools":
        for t in gw.list_tools(SERVICES[a.service].path):
            schema = t.get("inputSchema") or {}
            required = set(schema.get("required") or [])
            print(f"- {t['name']}: {(t.get('description') or '').strip().splitlines()[0][:120]}")
            for k, v in (schema.get("properties") or {}).items():
                print(f"    {'*' if k in required else ' '} {k} ({v.get('type')}): "
                      f"{(v.get('description') or '').replace(chr(10), ' ')[:100]}")
    elif a.cmd == "call":
        s = SERVICES[a.service]
        r = gw.call(s.path, a.tool, json.loads(a.arguments), points=s.points, refresh=a.refresh)
        print(f"{'缓存命中，0 分' if r['cached'] else f'花费 {s.points} 分'}")
        print(json.dumps(r["structured"] if r["structured"] is not None else r["text"], ensure_ascii=False)[:4000])
    elif a.cmd == "seed":
        s = SERVICES[a.service]
        raw = json.loads(Path(a.response_file).read_text("utf-8"))
        raw = raw.get("response", raw)  # 兼容 mcp_probe 的两种存档格式
        print(gw.seed(s.path, a.tool, json.loads(a.arguments), raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

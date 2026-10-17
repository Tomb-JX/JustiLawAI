"""运行状态板（监控 CLI）：单次运行进度 / 运行列表 / watch 常驻刷新。

用法：
  python research/discretion/unify/status.py                # 列出全部运行
  python research/discretion/unify/status.py --run latest   # 最近一次运行的详细板
  python research/discretion/unify/status.py --run s1-xxx --watch  # 2 秒刷新
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1 import data_root  # noqa: E402

RUNS = "s1_runs"


def _runs_root() -> Path:
    return data_root() / RUNS


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs() -> None:
    root = _runs_root()
    rows = []
    for d in sorted(root.glob("s1-*")):
        prog = _load(d / "progress.json") or {}
        summ = _load(d / "summary.json") or {}
        rows.append({
            "run": d.name, "phase": prog.get("phase", "done" if summ else "?"),
            "done": prog.get("done", summ.get("n", 0)), "total": prog.get("total", summ.get("n", 0)),
            "ok": prog.get("ok", summ.get("ok", 0)),
            "eta_min": prog.get("eta_min"), "cost": prog.get("cost_total", {}).get("cost"),
            "tokens": prog.get("cost_total", {}).get("tokens"),
        })
    print(f"{'run':<26}{'phase':<10}{'done/total':>12}{'ok':>6}{'eta_min':>9}{'tokens':>10}{'¥估':>8}")
    for r in rows:
        dt = f"{r['done']}/{r['total']}" if r['total'] else "-"
        print(f"{r['run']:<26}{r['phase']:<10}{dt:>12}{r['ok']:>6}"
              f"{str(r['eta_min'] if r['eta_min'] is not None else ''):>9}"
              f"{str(r['tokens'] or ''):>10}{str(r['cost'] or ''):>8}")


def show_run(run: str) -> None:
    d = _runs_root() / run
    prog = _load(d / "progress.json")
    if prog:
        bar = "#" * int(30 * prog["done"] / prog["total"]) if prog.get("total") else ""
        print(f"运行 {prog.get('run_id', run)}  [{prog['phase']}]  "
              f"[{bar:<30}] {prog['done']}/{prog['total']}"
              f"（ok {prog['ok']} / fail {prog['fail']} / 在飞 {prog['in_flight']}）")
        print(f"耗时 {prog['elapsed_min']}min 速率 {prog['rate_rpm']}件/分 ETA {prog['eta_min']}min  "
              f"延迟 p50/p90 = {prog['latency_ms_p50']}/{prog['latency_ms_p90']} ms")
        print(f"重试分布 {prog['attempts_dist']}  失败分类 {prog['error_categories']}")
        print(f"费用 {prog['cost_total']}")
        for model, m in (prog.get("tokens_by_model") or {}).items():
            print(f"  {model}: calls={m['calls']} prompt={m['prompt']} completion={m['completion']} ¥{m['cost']}")
        for e in prog.get("errors_recent", [])[-5:]:
            print(f"  [{e['ts']}] {e['provider']}/{e['cat']}: {e['error'][:80]}")
        return
    summ = _load(d / "summary.json")
    if summ:
        print(f"运行 {run} 已完成（无 progress.json，旧格式）：")
        print(json.dumps(summ, ensure_ascii=False, indent=1))
        return
    print(f"未找到 {run} 的进度或摘要")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="", help="运行 id 或 latest")
    ap.add_argument("--watch", action="store_true", help="2 秒刷新（前台常驻）")
    a = ap.parse_args()
    if not a.run:
        list_runs()
        return
    run = a.run
    if run == "latest":
        dirs = sorted(_runs_root().glob("s1-*"))
        run = dirs[-1].name if dirs else ""
    while True:
        show_run(run)
        if not a.watch:
            break
        time.sleep(2)
        print("\n" + "-" * 60)


if __name__ == "__main__":
    main()

"""发现层例行化（设计 §3.3 增量模式、§3.2 第二段、§9 M4）：一条命令跑完一周的发现流程。

  1 增量搜索   所有常规模板加 recency=week，顶到 50 条按特征词拆一层
  2 分诊       合并全部批次 → 交付目录与 domains.csv
  3 逐站精扫   域名库里有赌博文书、且近 --resweep-days 天没扫过的县级主域名，各跑一次 site:<主域名> 赌博；
               顶到 50 条的记为大栏目县，转第 5 步
  4 再分诊     把精扫结果并进来
  5 栏目扩展   新出现的富矿主机（n_target ≥ --expand-min-target）+ 精扫顶格的县；已扩展过的不重复抓
  6 增量交付   交付目录里 urls_new.tsv / columns_new.csv 只含本周新增；全量 urls.tsv / columns.csv 照常更新
  7 周报       交付目录 weekly_report.md；本目录 weekly-log.csv 追加一行计数（入库）

状态都在仓库外 $JUSTILAW_DATA_DIR/discover/state/：sweep_state.json、expand_state.json、
delivered_urls.txt、columns_master.csv。重跑幂等：搜索走缓存，已交付的不会再进 *_new。

用法（仓库根目录；需 QIANFAN_API_KEY，进程或 Windows 用户级环境变量）：
  python research/discretion/discover/weekly.py
  python research/discretion/discover/weekly.py --search-budget 40 --sweep-budget 40 --max-sites 40
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Callable

from expand import expand_hosts, load_domains, write_columns
from plan import load_config, seeds_incremental, seeds_sweep
from search import Budget, Cache, Client, Ledger, PRICE_CNY, api_key, data_root, run
from triage import DOMAINS_CSV, URL_FIELDS, run_triage

HERE = Path(__file__).resolve().parent
WEEKLY_LOG = HERE / "weekly-log.csv"
WEEKLY_FIELDS = ["date", "inc_calls", "sweep_calls", "est_cost_cny", "sites_swept", "sites_saturated",
                 "hosts_expanded", "new_columns_ok", "candidates", "deliverable_urls", "new_urls", "domains"]
# 跨省、跨系统的公共域名不做逐站精扫（扫出来是全国性内容）
NOT_COUNTY = {"gov.cn", "www.gov.cn", "jcy.gov.cn", "court.gov.cn", "npc.gov.cn", "12309.gov.cn", "spp.gov.cn"}


# ---------- 纯函数（有单测） ----------

def registrable_site(host: str) -> str | None:
    """主机名 → 用于 site: 的县级主域名：*.gov.cn 取最后三段（info.qinghexian.gov.cn → qinghexian.gov.cn）。"""
    labels = (host or "").lower().split(".")
    if labels[-2:] != ["gov", "cn"] or len(labels) < 3:
        return None
    site = ".".join(labels[-3:])
    return None if site in NOT_COUNTY else site


def pick_sweep_sites(domains: dict[str, dict], state: dict[str, dict], today: date, max_sites: int,
                     min_target: int = 1, resweep_days: int = 28) -> list[str]:
    totals: dict[str, int] = {}
    for host, r in domains.items():
        s = registrable_site(host)
        if s:
            totals[s] = totals.get(s, 0) + int(r.get("n_target") or 0)
    due = [s for s, n in totals.items() if n >= min_target and (
        s not in state or (today - date.fromisoformat(state[s]["date"])).days >= resweep_days)]
    return sorted(due, key=lambda s: (-totals[s], s))[:max_sites]


def sweep_results(rows: list[dict]) -> dict[str, dict]:
    """从执行器的 queries.csv 行里取每个站点的返回数与是否顶格。"""
    out: dict[str, dict] = {}
    for r in rows:
        qid = r.get("qid", "")
        if "|s=" not in qid or r.get("source") not in ("api", "cache"):
            continue
        site = qid.split("|s=")[1].split("|")[0]
        n = int(r.get("n") or 0)
        cur = out.setdefault(site, {"n": 0, "saturated": False})
        cur["n"] = max(cur["n"], n)
        cur["saturated"] = cur["saturated"] or r.get("saturated") == "unsplit"
    return out


def new_items(rows: list[dict], delivered: set[str], key: str) -> list[dict]:
    return [r for r in rows if r.get(key) and r[key] not in delivered]


def merge_columns(master: list[dict], fresh: list[dict]) -> tuple[list[dict], list[dict]]:
    """按县级主域名合并栏目表：新结果覆盖旧的（定位可能变好）；返回 (合并后全量, 本周新增或状态变化的行)。"""
    by_site = {registrable_site(r["domain"]) or r["domain"]: r for r in master}
    changed = []
    for r in fresh:
        k = registrable_site(r["domain"]) or r["domain"]
        old = by_site.get(k)
        if old is None or old.get("status") != r.get("status") or old.get("entry_url") != r.get("entry_url"):
            changed.append(r)
        by_site[k] = r
    return list(by_site.values()), changed


# ---------- 状态读写 ----------

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def read_csv(path: Path, delimiter: str = ",") -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def write_tsv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def bootstrap_from_previous(root: Path, state_dir: Path, expand_state: dict) -> None:
    """把此前单独运行 expand.py 产出的最新 columns.csv 作为主表与已扩展状态。"""
    prev = sorted((root / "out").glob("*/columns.csv"))
    if not prev:
        return
    rows = read_csv(prev[-1])
    for r in rows:
        expand_state[registrable_site(r["domain"]) or r["domain"]] = {"date": prev[-1].parent.name, "status": r["status"]}
    write_columns(rows, state_dir, "columns_master.csv")


# ---------- 编排 ----------

def weekly(*, root: Path, client: Client | None, search_budget: int, sweep_budget: int, max_sites: int,
           daily_cap: int, expand_min_target: int, resweep_days: int, today: date,
           domains_csv: Path = DOMAINS_CSV, weekly_log: Path | None = WEEKLY_LOG,
           expand_fn: Callable[..., list[dict]] = expand_hosts) -> dict:
    cfg = load_config()
    cache, ledger = Cache(root / "cache"), Ledger(root / "ledger.csv")
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    stamp = today.strftime("%Y%m%d")
    offline = client is None

    def batch(name: str, queries, budget_n: int):
        budget = None if offline else Budget(budget_n, budget_n * PRICE_CNY, daily_cap, ledger)
        out = root / "runs" / f"weekly-{stamp}-{name}"
        s = run(queries, cfg, cache=cache, budget=budget, client=client, offline=offline, max_depth=1,
                out_dir=out, seen_path=root / "seen_urls.txt")
        return s, read_csv(out / "queries.csv")

    # 0 首次例行：此前手工交付过的 urls.tsv 记为已交付，避免重复进 urls_new
    delivered_path = state_dir / "delivered_urls.txt"
    if not delivered_path.exists():
        prev = sorted((root / "out").glob("*/urls.tsv"))
        seeded = [r["url"] for r in read_csv(prev[-1], delimiter="\t")] if prev else []
        delivered_path.write_text("".join(u + "\n" for u in seeded), encoding="utf-8")
    # 1 增量搜索
    inc, _ = batch("inc", seeds_incremental(cfg, "week"), search_budget)
    # 2 分诊（刷新域名库，供精扫选站）
    run_triage(root, domains_csv)
    # 3 逐站精扫
    sweep_state = load_json(state_dir / "sweep_state.json")
    sites = pick_sweep_sites(load_domains(domains_csv), sweep_state, today, max_sites, resweep_days=resweep_days)
    sw, sw_rows = batch("sweep", seeds_sweep(cfg, sites), sweep_budget) if sites else ({"api_calls": 0}, [])
    results = sweep_results(sw_rows)
    for s, r in results.items():
        sweep_state[s] = {"date": today.isoformat(), **r}
    save_json(state_dir / "sweep_state.json", sweep_state)
    saturated = sorted(s for s, r in results.items() if r["saturated"])
    # 4 再分诊
    cands, out_dir, tstats = run_triage(root, domains_csv)
    # 5 栏目扩展：新富矿主机 + 精扫顶格的县，已扩展过的县跳过
    doms = load_domains(domains_csv)
    expand_state = load_json(state_dir / "expand_state.json")
    master_path = state_dir / "columns_master.csv"
    if not expand_state and not master_path.exists():
        bootstrap_from_previous(root, state_dir, expand_state)  # 首次例行：沿用 M3 手工跑出的栏目，不重复抓
    targets = [h for h, r in doms.items()
               if (registrable_site(h) or h) not in expand_state
               and (int(r.get("n_target") or 0) >= expand_min_target or registrable_site(h) in saturated)]
    fresh = expand_fn(targets, cands, doms) if targets else []
    for r in fresh:
        expand_state[registrable_site(r["domain"]) or r["domain"]] = {"date": today.isoformat(), "status": r["status"]}
    save_json(state_dir / "expand_state.json", expand_state)
    master, changed = merge_columns(read_csv(master_path), fresh)
    write_columns(master, state_dir, "columns_master.csv")
    write_columns(master, out_dir, "columns.csv")
    write_columns(changed, out_dir, "columns_new.csv")
    # 6 增量交付
    urls = read_csv(out_dir / "urls.tsv", delimiter="\t")
    delivered = set(delivered_path.read_text(encoding="utf-8").splitlines())
    new_urls = new_items(urls, delivered, "url")
    write_tsv(out_dir / "urls_new.tsv", new_urls, URL_FIELDS)
    if new_urls:
        with open(delivered_path, "a", encoding="utf-8") as f:
            f.writelines(r["url"] + "\n" for r in new_urls)
    # 7 周报
    calls_inc, calls_sw = inc.get("api_calls", 0), sw.get("api_calls", 0)
    row = {
        "date": today.isoformat(), "inc_calls": calls_inc, "sweep_calls": calls_sw,
        "est_cost_cny": round((calls_inc + calls_sw) * PRICE_CNY, 3), "sites_swept": len(results),
        "sites_saturated": len(saturated), "hosts_expanded": len(fresh),
        "new_columns_ok": sum(r.get("status") == "ok" for r in changed), "candidates": tstats["candidates"],
        "deliverable_urls": len(urls), "new_urls": len(new_urls), "domains": tstats["domains"],
    }
    report = [f"# 发现层周报 {today.isoformat()}", "", "| 项 | 数 |", "|---|---|"]
    report += [f"| {k} | {v} |" for k, v in row.items() if k != "date"]
    report += ["", f"顶格（转整栏收割）的县：{'、'.join(saturated) or '无'}",
               f"本周新增或变化的栏目：{len(changed)}（见 columns_new.csv）",
               f"增量搜索停止原因：{inc.get('stop_reason') or '无'}；精扫停止原因：{sw.get('stop_reason') or '无'}"]
    (out_dir / "weekly_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if weekly_log is not None:
        new = not weekly_log.exists()
        with open(weekly_log, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=WEEKLY_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
    return {**row, "out_dir": str(out_dir), "saturated": saturated}


def main() -> None:
    ap = argparse.ArgumentParser(description="发现层每周例行")
    ap.add_argument("--search-budget", type=int, default=40, help="增量搜索最多调用次数")
    ap.add_argument("--sweep-budget", type=int, default=40, help="逐站精扫最多调用次数")
    ap.add_argument("--max-sites", type=int, default=40, help="本周最多精扫的县级主域名数")
    ap.add_argument("--daily-cap", type=int, default=150, help="当日累计调用上限（跨运行）")
    ap.add_argument("--expand-min-target", type=int, default=3, help="n_target ≥ 该值的新主机做栏目扩展")
    ap.add_argument("--resweep-days", type=int, default=28, help="同一站点两次精扫的最短间隔（天）")
    ap.add_argument("--offline", action="store_true", help="只用缓存，不联网（演练用）")
    args = ap.parse_args()
    key = None if args.offline else api_key()
    if not args.offline and not key:
        raise SystemExit("缺少 QIANFAN_API_KEY（进程环境变量或 Windows 用户级环境变量）；演练请加 --offline")
    result = weekly(root=data_root(), client=Client(key) if key else None, search_budget=args.search_budget,
                    sweep_budget=args.sweep_budget, max_sites=args.max_sites, daily_cap=args.daily_cap,
                    expand_min_target=args.expand_min_target, resweep_days=args.resweep_days, today=date.today())
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()

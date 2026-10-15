"""发现层 L2 搜索执行器：千帆「百度搜索」API + 缓存 + 预算闸门 + 限速 + 饱和拆分（设计 §3.2–3.3）。

  缓存    请求体规范化 SHA-256 为键，响应存 $JUSTILAW_DATA_DIR/discover/cache/；命中不付费。
          只缓存成功响应（HTTP 200 且无错误码），失败的下次重试。
  预算    三道闸：本次调用数 --budget、本次估算费用 --max-cost（¥0.036/次）、
          当日累计调用 --daily-cap（跨运行，记在 discover/ledger.csv；默认 50≈每月免费 1500 的日均）。
          任一触顶即停，队列里剩下的查询记为 deferred，下次可续跑（已跑的走缓存）。
  限速    两次请求间隔 ≥ --min-interval 秒；429/5xx/网络异常指数退避重试，最多 3 次（每次尝试都计入预算）。
  拆分    结果数 ≥ top_k 视为被截断，按 plan.split() 下钻，深度上限 --max-depth；到达上限仍满的记为 saturated_unsplit。

用法（仓库根目录；联网运行需 QIANFAN_API_KEY——进程环境变量，或用 setx 设的 Windows 用户级环境变量）：
  python research/discretion/discover/search.py import-probe <M0 探针输出目录>   # 把探针响应灌进缓存
  python research/discretion/discover/search.py run --templates fy70,cf82 --offline   # 只用缓存，离线回放
  python research/discretion/discover/search.py run --templates fy70,cf70 --regions 浙江,河北 --budget 10
产出：$JUSTILAW_DATA_DIR/discover/runs/<批次>/{queries.csv, hits.jsonl, summary.json}；
      本目录 run-log.csv 追加一行批次汇总（入库，只含计数）。hits.jsonl 含摘录（可能有个人信息），只在仓库外。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from plan import Query, body_key, load_config, seeds, split

API = "https://qianfan.baidubce.com/v2/ai_search/web_search"
PRICE_CNY = 0.036
HERE = Path(__file__).resolve().parent
RUN_LOG = HERE / "run-log.csv"
RUN_LOG_FIELDS = [
    "date", "batch", "mode", "templates", "regions", "max_depth", "queries_done", "cache_hits",
    "api_calls", "est_cost_cny", "results", "unique_urls", "new_urls", "gambling_snippets",
    "saturated_unsplit", "errors", "deferred", "stop_reason",
]
QUERY_FIELDS = ["qid", "depth", "source", "status", "error", "n", "gov", "gambling", "saturated", "children"]

Transport = Callable[[dict, str], "tuple[int, dict]"]


def api_key() -> str | None:
    """先读当前进程环境变量；没有时读 Windows 用户级环境变量（注册表 HKCU\\Environment）。
    setx 写入的变量要重启应用才进入新进程的环境，直接读注册表可免重启。Key 不落任何文件。"""
    key = os.environ.get("QIANFAN_API_KEY")
    if key or sys.platform != "win32":
        return key
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, "QIANFAN_API_KEY")[0] or None
    except OSError:
        return None


def data_root() -> Path:
    return Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research")) / "discover"


def ok_response(status: int, resp: dict) -> bool:
    return status == 200 and not (resp or {}).get("code")


class Cache:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, key: str, body: dict, status: int, resp: dict) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"request": body, "status": status, "response": resp, "fetched_at": datetime.now().isoformat(timespec="seconds")}
        p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


class Ledger:
    """每次真实调用记一行（时间、查询、尝试次数），用于跨运行的每日上限。"""

    def __init__(self, path: Path):
        self.path = path

    def today_calls(self) -> int:
        if not self.path.exists():
            return 0
        today = datetime.now().strftime("%Y-%m-%d")
        with open(self.path, encoding="utf-8", newline="") as f:
            return sum(int(r["attempts"]) for r in csv.DictReader(f) if r["time"].startswith(today))

    def add(self, qid: str, attempts: int) -> None:
        new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "qid", "attempts"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), qid, attempts])


class Budget:
    def __init__(self, max_calls: int, max_cost: float, daily_cap: int, ledger: Ledger):
        self.max_calls, self.max_cost, self.daily_cap, self.ledger = max_calls, max_cost, daily_cap, ledger
        self.calls = 0

    def allow(self) -> tuple[bool, str]:
        if self.calls + 1 > self.max_calls:
            return False, f"本次调用数达到 --budget {self.max_calls}"
        if (self.calls + 1) * PRICE_CNY > self.max_cost + 1e-9:
            return False, f"本次估算费用将超过 --max-cost ¥{self.max_cost}"
        if self.ledger.today_calls() + 1 > self.daily_cap:
            return False, f"今日累计调用达到 --daily-cap {self.daily_cap}"
        return True, ""

    def spend(self, qid: str, attempts: int) -> None:
        self.calls += attempts
        self.ledger.add(qid, attempts)


def requests_transport(body: dict, key: str) -> tuple[int, dict]:
    import requests

    s = requests.Session()
    s.trust_env = False
    r = s.post(API, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    return r.status_code, (r.json() if r.content else {})


class Client:
    def __init__(self, key: str, transport: Transport = requests_transport, min_interval: float = 1.0,
                 max_retries: int = 3, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.key, self.transport, self.min_interval, self.max_retries = key, transport, min_interval, max_retries
        self.clock, self.sleep = clock, sleep
        self._last: float | None = None

    def _wait(self) -> None:
        if self._last is not None:
            gap = self.min_interval - (self.clock() - self._last)
            if gap > 0:
                self.sleep(gap)
        self._last = self.clock()

    def post(self, body: dict) -> tuple[int, dict, int]:
        """返回 (HTTP 状态, 响应 JSON, 尝试次数)。"""
        status, resp = 0, {}
        for attempt in range(1, self.max_retries + 2):
            self._wait()
            try:
                status, resp = self.transport(body, self.key)
            except Exception as e:  # noqa: BLE001 - 网络异常按可重试处理
                status, resp = 0, {"code": "NetworkError", "message": str(e)[:200]}
            if status == 200 or (status and status < 500 and status != 429):
                return status, resp, attempt
            if attempt <= self.max_retries:
                self.sleep(2 ** attempt)
        return status, resp, self.max_retries + 1


def summarize_refs(refs: list[dict]) -> tuple[int, int]:
    gov = sum((urlparse(r.get("url", "")).hostname or "").endswith("gov.cn") for r in refs)
    gambling = sum("赌" in (r.get("content") or r.get("snippet") or "") + r.get("title", "") for r in refs)
    return gov, gambling


def run(queries: list[Query], cfg: dict, *, cache: Cache, budget: Budget | None, client: Client | None,
        offline: bool, max_depth: int, out_dir: Path, seen_path: Path) -> dict:
    top_k = cfg["api"]["top_k"]
    queue: deque[Query] = deque(queries)
    rows: list[dict] = []
    hits: dict[str, dict] = {}
    stop_reason, deferred = "", 0
    today = datetime.now().strftime("%Y-%m-%d")

    while queue:
        q = queue.popleft()
        body = q.body(cfg)
        key = body_key(body)
        rec = cache.get(key)
        source = "cache"
        if rec is None:
            if offline:
                rows.append({"qid": q.qid, "depth": q.depth, "source": "miss"})
                continue
            allowed, why = budget.allow()
            if not allowed:
                stop_reason, deferred = why, len(queue) + 1
                rows.append({"qid": q.qid, "depth": q.depth, "source": "deferred"})
                rows += [{"qid": x.qid, "depth": x.depth, "source": "deferred"} for x in queue]
                break
            status, resp, attempts = client.post(body)
            budget.spend(q.qid, attempts)
            source = "api"
            if ok_response(status, resp):
                cache.put(key, body, status, resp)
            rec = {"status": status, "response": resp}

        resp = rec.get("response") or {}
        refs = resp.get("references") or []
        error = "" if ok_response(rec["status"], resp) else (resp.get("code") or f"HTTP {rec['status']}")
        saturated = len(refs) >= top_k
        children = split(q, cfg) if saturated and not error and q.depth < max_depth else []
        queue.extend(children)
        gov, gambling = summarize_refs(refs)
        for r in refs:
            url = r.get("url")
            if url and url not in hits:
                hits[url] = {
                    "url": url, "title": r.get("title", ""), "date": r.get("date", ""),
                    "website": r.get("website", ""), "content": r.get("content") or r.get("snippet") or "",
                    "query_id": q.qid, "template": q.template, "found_at": today,
                }
        rows.append({"qid": q.qid, "depth": q.depth, "source": source, "status": rec["status"], "error": error,
                     "n": len(refs), "gov": gov, "gambling": gambling,
                     "saturated": "unsplit" if saturated and not children else ("split" if children else ""),
                     "children": len(children)})

    seen = set(seen_path.read_text(encoding="utf-8").splitlines()) if seen_path.exists() else set()
    new_urls = [u for u in hits if u not in seen]
    if new_urls and not offline:  # 离线回放不改动「已见 URL」基线
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seen_path, "a", encoding="utf-8") as f:
            f.writelines(u + "\n" for u in new_urls)

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "queries.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=QUERY_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(out_dir / "hits.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(h, ensure_ascii=False) + "\n" for h in hits.values())
    done = [r for r in rows if r["source"] in ("api", "cache")]
    summary = {
        "queries_done": len(done),
        "cache_hits": sum(r["source"] == "cache" for r in rows),
        "cache_misses": sum(r["source"] == "miss" for r in rows),
        "api_calls": budget.calls if budget else 0,
        "est_cost_cny": round((budget.calls if budget else 0) * PRICE_CNY, 3),
        "results": sum(r.get("n", 0) for r in done),
        "unique_urls": len(hits),
        "new_urls": len(new_urls),
        "gambling_snippets": sum("赌" in h["content"] + h["title"] for h in hits.values()),
        "saturated_unsplit": sum(r.get("saturated") == "unsplit" for r in rows),
        "errors": sum(bool(r.get("error")) for r in rows),
        "deferred": deferred,
        "stop_reason": stop_reason,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def import_probe(probe_dir: Path, cache: Cache) -> int:
    n = 0
    for p in sorted(probe_dir.glob("T*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if ok_response(rec.get("status", 0), rec.get("response") or {}):
            cache.put(body_key(rec["request"]), rec["request"], rec["status"], rec["response"])
            n += 1
    return n


def append_run_log(path: Path, row: dict) -> None:
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ip = sub.add_parser("import-probe", help="把 M0 探针的成功响应灌进缓存")
    ip.add_argument("probe_dir", type=Path)
    rp = sub.add_parser("run", help="执行查询（饱和即拆分）")
    rp.add_argument("--templates", default="", help="逗号分隔的模板 id，默认全部")
    rp.add_argument("--regions", default="", help="逗号分隔的省级名称，默认全国")
    rp.add_argument("--max-depth", type=int, default=1, help="拆分深度上限（0 = 不拆分）")
    rp.add_argument("--budget", type=int, default=20, help="本次最多真实调用次数")
    rp.add_argument("--max-cost", type=float, default=1.0, help="本次最多估算费用（元）")
    rp.add_argument("--daily-cap", type=int, default=50, help="当日累计调用上限（跨运行）")
    rp.add_argument("--min-interval", type=float, default=1.0, help="两次请求最小间隔（秒）")
    rp.add_argument("--offline", action="store_true", help="只用缓存，不联网（缺缓存的查询记为 miss）")
    rp.add_argument("--batch", default="", help="批次名，默认时间戳")
    args = ap.parse_args()

    root = data_root()
    cache = Cache(root / "cache")
    if args.cmd == "import-probe":
        print(f"灌入缓存 {import_probe(args.probe_dir, cache)} 条 → {cache.root}")
        return

    cfg = load_config()
    templates = [t for t in args.templates.split(",") if t] or None
    regions = [r for r in args.regions.split(",") if r] or None
    queries = seeds(cfg, templates, regions)
    client = budget = None
    if not args.offline:
        key = api_key()
        if not key:
            sys.exit("缺少 QIANFAN_API_KEY（进程环境变量或 Windows 用户级环境变量）；只想回放缓存请加 --offline")
        client = Client(key, min_interval=args.min_interval)
        budget = Budget(args.budget, args.max_cost, args.daily_cap, Ledger(root / "ledger.csv"))
    batch = args.batch or datetime.now().strftime("%Y%m%d-%H%M%S") + ("-offline" if args.offline else "")
    out_dir = root / "runs" / batch
    summary = run(queries, cfg, cache=cache, budget=budget, client=client, offline=args.offline,
                  max_depth=args.max_depth, out_dir=out_dir, seen_path=root / "seen_urls.txt")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"明细 → {out_dir}")
    if summary["api_calls"]:  # 纯缓存回放不记入批次日志（日志统计的是真实花费与新增）
        append_run_log(RUN_LOG, {"date": datetime.now().strftime("%Y-%m-%d"), "batch": batch, "mode": "online",
                                 "templates": args.templates or "全部", "regions": args.regions or "全国",
                                 "max_depth": args.max_depth, **summary})


if __name__ == "__main__":
    main()

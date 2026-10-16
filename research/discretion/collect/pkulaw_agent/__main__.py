"""法宝作业台命令行入口（M0–M5）。

用法（任选其一，建议直接运行本文件）：
  doctor                                   环境自检（不联网；含 profile 锁、session.json、CDP 探测）
  serve [--port 9222]                      长驻窗口：一个浏览器跑完所有命令（CDP 接管，不闪断）
  login [--hold]                           稳定登录：窗口在登录成功前不会关闭；成功后写 session.json
  recon [--tag 20261016] [--seconds 0]     登录后捕获 XHR（脱敏）+ 回放固化响应字段
  cluster --lib apy [--dim CategoryNew]    拉筛选维度与 id 映射
  call --path … --body …                   任意 API 直调（agent 探索用）
  search --plan plan.json                  检索（分页/饱和拆分）→ results.jsonl
  fetch --run <run_dir> [--ingest]         零配额抓正文 → .txt + 形态预探（可接着走解析链）
  download --run <run_dir> [--manual]      勾选/逐条 → 下载文件（自动，--manual 人工兜底）
  jobs from-mcp --cache <缓存目录> --out j.jsonl   MCP 结果（含原文链接）→ 作业单（0 积分）
  jobs from-csv --csv worklist.csv --out j.jsonl   清洗清单 → 作业单
  run --jobs j.jsonl [--dry-run] [--cap 30]        打开→抓正文→六校验→（通过才）限额下载→报告
  harvest --plan plan.json                 一条命令串完 search→fetch[→download]

边界（design §3 / 协调 2026-10-16 21:24）：只用站内检索/浏览/导出功能；遇验证码或风控停下由人处理，
不绕过；单账号；请求间隔 ≥1.5s；下载显式 --cap 且不超账户限额；凭据与 profile 不进仓库、不入对话。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pkulaw_agent"

from pkulaw_agent import __version__, api as api_mod, session as sess  # noqa: E402

BROWSER_PATHS = {
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "msedge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
               r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
}


def _print_json(data, max_chars: int = 4000) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…（截断，共 {len(text)} 字符；需要全量用 --save）"
    print(text)


# ---- doctor ----
def cmd_doctor(a: argparse.Namespace) -> int:
    print(f"pkulaw_agent v{__version__}")
    print(f"Python: {sys.version.split()[0]}")
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
        print("playwright: 已安装")
    except Exception as exc:  # noqa: BLE001
        print(f"playwright: 未安装（{exc}）→ 运行：python -m pip install playwright")
    for name, paths in BROWSER_PATHS.items():
        found = next((p for p in paths if Path(p).exists()), "")
        print(f"{name}: {found or '未找到（将尝试用 playwright 的 channel 定位）'}")
    root = sess.data_dir()
    profile = sess.profile_dir()
    print(f"数据目录: {root}  {'可写' if os.access(root, os.W_OK) else '不存在或不可写'}")
    print(f"浏览器 profile: {profile}  {'已存在（可能已登录过）' if profile.exists() else '未创建'}")
    locks = sess.profile_lock_files(profile)
    if locks:
        print(f"profile 锁文件: {locks}（Chrome 正在使用或异常残留；启动失败先关掉残留 Chrome）")
    info = sess.load_session_info()
    print(f"session.json: {json.dumps(info, ensure_ascii=False) if info else '无（还没跑过 login）'}")
    v = sess.cdp_probe(sess.DEFAULT_CDP_PORT)
    print(f"CDP 端口 {sess.DEFAULT_CDP_PORT}: "
          + ("在（serve 运行中——命令会自动接管该窗口，不新开不闪断）"
             if v else "未开（正常；需要单窗口长驻可跑 serve）"))
    return 0


def _wait_tick(s, seconds: float) -> None:
    """驱动 Playwright 事件循环的等待（页面被关时退回真睡眠）。"""
    try:
        s.page.wait_for_timeout(int(seconds * 1000))
    except Exception:  # noqa: BLE001
        time.sleep(seconds)


def _find_browser(name: str) -> str:
    for p in BROWSER_PATHS.get(name, []):
        if Path(p).exists():
            return p
    return ""


# ---- login ----
def cmd_login(a: argparse.Namespace) -> int:
    """稳定登录（v1.1）：窗口在登录成功前不会关闭；任何异常都不关窗；成功后写 session.json。

    退出条件：登录成功且（--hold 保持 / --grace 秒后自动关）；--timeout 到点；用户关窗；Ctrl+C。
    """
    hold = a.hold if a.hold is not None else sys.stdin.isatty()
    with sess.Session(browser=a.browser, cdp_port=a.cdp_port) as s:
        try:
            s.open_entry(a.entry)
        except sess.SecurityChallenge as exc:
            print(f"{exc}\n（窗口保持打开：请在窗口中人工完成验证，工具会继续等待。）")
        tok = s.token()
        if tok:
            print(f"检测到已有登录态：{sess.mask_token(tok)}  到期约 {sess.jwt_exp_hint(tok) or '未知'}")
        else:
            print("未检测到登录态。已打开稳定登录窗口——请在此窗口中完成登录")
            print("（账号密码 / 微信扫码 / 验证码均可；窗口在登录成功前不会关闭，每 3 秒自动检测）。")
        api = api_mod.PkulawApi(s)
        deadline = time.time() + a.timeout if a.timeout and a.timeout > 0 else None
        ok = False
        while not ok:
            if s.page_closed():
                print("浏览器窗口已被关闭。若已完成登录可直接重跑任意命令；否则重跑 login。")
                return 3
            tok = s.token()
            if not tok:
                _wait_tick(s, 3)
                if deadline and time.time() > deadline:
                    print("已到 --timeout 上限（窗口保持打开 30 秒；完成后重跑 login 即可）。")
                    _wait_tick(s, 30)
                    return 2
                continue
            try:
                api.verify_login(a.lib)
                ok = True
            except PermissionError:
                print("token 已存在但校验失败（多为过期）——请在窗口中重新登录，继续等待……")
                _wait_tick(s, 3)
            except sess.SecurityChallenge:
                print("页面处于安全验证：请在窗口中按提示人工完成（工具不绕过），继续等待……")
                _wait_tick(s, 5)
            except Exception as exc:  # noqa: BLE001
                print(f"校验暂时失败（{type(exc).__name__}: {exc}）……20 秒后自动重试；窗口保持打开。")
                _wait_tick(s, 20)
            if deadline and time.time() > deadline and not ok:
                print("已到 --timeout 上限（窗口保持打开 30 秒）。")
                _wait_tick(s, 30)
                return 2
        tok = s.token()
        info = {"checked_at": time.strftime("%Y-%m-%d %H:%M"),
                "token_exp": sess.jwt_exp_hint(tok), "lib_ok": a.lib,
                "account": s.account_hint(), "mode": s.mode}
        sess.save_session_info(**info)
        print(f"✅ 登录成功：{sess.mask_token(tok)}  到期约 {info['token_exp'] or '未知'}"
              f"  机构线索：{info['account'] or '（未读到）'}")
        print("登录态已固化（profile）+ session.json 已更新；后续命令免登录。")
        if hold:
            if sys.stdin.isatty():
                try:
                    input("窗口保持打开——完成其他操作后回终端按回车关闭窗口（或 Ctrl+C）…")
                except EOFError:
                    pass
            else:
                print("窗口保持打开中（agent 模式；Ctrl+C 或关闭窗口结束本命令）")
                try:
                    while not s.page_closed():
                        _wait_tick(s, 15)
                except KeyboardInterrupt:
                    pass
        else:
            print(f"窗口将在 {a.grace} 秒后自动关闭（--hold 可保持窗口）")
            _wait_tick(s, a.grace)
        return 0


# ---- recon ----
def cmd_recon(a: argparse.Namespace) -> int:
    from pkulaw_agent.api import PkulawApi
    from pkulaw_agent.recon import Recorder, collect_replays, scrub_keys

    with sess.Session(browser=a.browser) as s:
        s.open_entry(a.entry)
        tok = s.token()
        if not tok:
            print("未登录：请先在窗口中登录（或先跑 login 命令）。")
            tok = s.wait_for_login(a.timeout)
        api = api_mod.PkulawApi(s)
        try:
            api.verify_login(a.lib)
            print(f"登录态校验通过（{a.lib} 库可检索）。")
        except Exception as exc:  # noqa: BLE001
            print(f"注意：登录态校验未通过（{exc}）——仍继续捕获，但请确认窗口内可正常检索。")
        rec = Recorder(s, tag=a.tag)
        rec.start()
        print("\n请在窗口中依次做这三件事（工具只旁观记录，不动你的操作）：")
        print("  ① 到行政执法库页做一次检索（带上你要用的筛选：执法地域 / 执法机关 / 公布日期）")
        print("  ② 打开一篇有正文格式的记录详情页（正文在“处罚结果”栏的那种）")
        print("  ③ 若方便，点一次该记录的“下载”。若不想此时消耗配额，可跳过")
        if a.seconds > 0:
            print(f"\n将在 {a.seconds}s 后自动结束捕获…")
            waited = 0
            while waited < a.seconds:
                s.page.wait_for_timeout(1000)
                waited += 1
        elif sys.stdin.isatty():
            try:
                input("\n做完后回到本终端按回车结束捕获…")
            except EOFError:
                pass
        else:
            print("\n（非交互终端，300s 后自动结束）")
            waited = 0
            while waited < 300:
                s.page.wait_for_timeout(1000)
                waited += 1
        rec.stop()

        # 回放：事件回调读响应体有竞态（CDP 偶报 No resource with given identifier），
        # 用页面内 fetch 重发同样的请求，确定性取得完整响应（搜索是只读操作）
        if a.replay and s.token():
            replays = collect_replays(rec.out_path, limit=a.max_replay)
            if replays:
                print(f"\n回放 {len(replays)} 个 API 请求以固化响应字段…")
                api = PkulawApi(s, min_interval_s=1.5)
                results = []
                for r in replays:
                    try:
                        data = api.call(r["path"], r["body"])
                        results.append({**r, "ok": True, "resp": scrub_keys(data, depth=3)})
                        keys = sorted(data)[:12] if isinstance(data, dict) else type(data).__name__
                        print(f"  ✓ {r['path']} → {keys}")
                    except Exception as exc:  # noqa: BLE001
                        results.append({**r, "ok": False, "error": str(exc)})
                        print(f"  ✗ {r['path']} → {exc}")
                        if "风控" in str(exc):
                            print("  触发风控：按红线立即停止回放。")
                            break
                out = s.root / "recon" / f"replay-{rec.tag}.json"
                out.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                print(f"回放结果 → {out}")
        elif a.replay:
            print("\n未登录或无 token，跳过回放（回放需要登录态）。")
        print("\n下一步：把 recon JSONL + replay JSON 交给模型组固化字段映射（filters-apy.json），即可进入 M2。")
        return 0


# ---- cluster ----
def cmd_cluster(a: argparse.Namespace) -> int:
    with sess.Session(browser=a.browser) as s:
        s.open_entry(a.lib)
        tok = s.token()
        if not tok:
            print("未登录：请先在窗口中登录（或先跑 login 命令）。")
            s.wait_for_login(a.timeout)
        api = api_mod.PkulawApi(s)
        data = api.cluster(a.lib, a.dim)
        out = s.root / "recon" / f"filters-{a.lib}-{a.dim or 'all'}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已保存 → {out}")
        _print_json(data, max_chars=a.max_chars)
        return 0


# ---- call ----
def cmd_call(a: argparse.Namespace) -> int:
    body_text = a.body
    if body_text and body_text.startswith("@"):
        body_text = Path(body_text[1:]).read_text(encoding="utf-8")
    body = json.loads(body_text) if body_text else {}
    with sess.Session(browser=a.browser) as s:
        s.open_entry(a.entry)
        tok = s.token()
        if not tok:
            print("未登录：请先在窗口中登录（或先跑 login 命令）。")
            s.wait_for_login(a.timeout)
        api = api_mod.PkulawApi(s)
        data = api.call(a.path, body)
        if a.save:
            Path(a.save).parent.mkdir(parents=True, exist_ok=True)
            Path(a.save).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
            print(f"已保存 → {a.save}")
        _print_json(data, max_chars=a.max_chars)
        return 0


def _ensure_login(s, timeout: int, *, entry: str = "apy") -> None:
    """打开发令库入口并确保有 token；没有就等用户手动登录。"""
    s.open_entry(entry)
    if not s.token():
        print("未登录：请在打开的浏览器窗口中完成登录（账号密码 / 微信扫码 / 验证码均可）。")
        s.wait_for_login(timeout)


def cmd_search(a: argparse.Namespace) -> int:
    import time as _time
    from pathlib import Path as _Path

    from pkulaw_agent.search import (expand_runs, load_plan, plan_template,
                                     run_search)
    if a.template:
        print(json.dumps(plan_template(), ensure_ascii=False, indent=2))
        return 0
    if a.plan:
        plan = load_plan(_Path(a.plan))
        batch = a.batch or plan.get("batch") or _time.strftime("%Y%m%d")
    else:
        if not a.term:
            print("需要 --plan 或（--lib 与 --term）；或 --template 看作业单格式")
            return 1
        plan = {"lib": a.lib, "batch": a.batch or _time.strftime("%Y%m%d"),
                "runs": [{"terms": [a.term], "region": a.region,
                          "window": [x.strip() for x in a.window.split(":")] if a.window else []}]}
        batch = plan["batch"]
    out_root = (_Path(a.out) if a.out
                else sess.data_dir() / "inbox" / "pkulaw" / batch / "search")
    runs = expand_runs(plan)
    if a.run_id:
        runs = [r for r in runs if a.run_id in r["id"]] or runs
    search_cfg = plan.get("search", {})
    with sess.Session(browser=a.browser) as s:
        _ensure_login(s, a.timeout, entry=plan["lib"] if plan["lib"] in sess.LIB_ENTRY else "apy")
        api = api_mod.PkulawApi(s, min_interval_s=a.interval)
        for run in runs:
            run_dir = out_root / run["id"].replace("/", "_")
            run_search(api, plan, run, run_dir,
                       page_size=a.page_size or search_cfg.get("page_size", 50),
                       max_pages=a.max_pages or search_cfg.get("max_pages", 40),
                       limit=a.limit or search_cfg.get("limit", 500),
                       order_by=a.order_by or search_cfg.get("order_by", ""),
                       split=plan.get("split"), dump_bodies=a.dump_body)
    print(f"产物目录：{out_root}")
    return 0


def cmd_fetch(a: argparse.Namespace) -> int:
    from pathlib import Path as _Path

    from pkulaw_agent.fetch import fetch_run, run_ingest
    run_dir = _Path(a.run)
    if not (run_dir / "results.jsonl").exists():
        print(f"{run_dir} 下没有 results.jsonl（先跑 search）")
        return 1
    with sess.Session(browser=a.browser) as s:
        _ensure_login(s, a.timeout)
        summary = fetch_run(s, run_dir, limit=a.limit, min_interval_s=a.min_interval,
                            keep_other=not a.only_narrative)
    if a.ingest:
        rc = run_ingest(run_dir / "fetch", _Path(a.ingest_out) if a.ingest_out
                        else run_dir / "ingest", harvest_date=a.harvest_date,
                        batch=run_dir.name)
        if rc != 0:
            print(f"解析链返回码 {rc}，请查看输出")
    print(f"抓取计数：{summary['counters']}")
    return 0


def cmd_download(a: argparse.Namespace) -> int:
    import time as _time
    from pathlib import Path as _Path

    from pkulaw_agent.download import download_results_page, download_run, ui_search
    with sess.Session(browser=a.browser) as s:
        _ensure_login(s, a.timeout, entry=a.lib)
        if a.run:
            run_dir = _Path(a.run)
            out_dir = _Path(a.out) if a.out else run_dir / "downloads"
            download_run(s, run_dir, out_dir, cap=a.cap, min_interval_s=a.interval,
                         manual=a.manual, fmt=a.format)
        else:
            if a.ui_search:
                if not a.term:
                    print("--ui-search 需要 --term")
                    return 1
                ui_search(s.page, a.term, lib=a.lib)
                url = s.page.url
            elif a.url:
                url = a.url
            else:
                print("需要 --run / --url / --ui-search 之一")
                return 1
            out_dir = (_Path(a.out) if a.out else
                       sess.data_dir() / "inbox" / "pkulaw" / (a.batch or _time.strftime("%Y%m%d"))
                       / "downloads")
            download_results_page(s, url, out_dir, pages=a.pages, cap=a.cap,
                                  manual=a.manual, fmt=a.format)
    return 0


def cmd_harvest(a: argparse.Namespace) -> int:
    import time as _time
    from pathlib import Path as _Path

    from pkulaw_agent.fetch import fetch_run, run_ingest
    from pkulaw_agent.search import expand_runs, load_plan, plan_template, run_search
    if a.template:
        print(json.dumps(plan_template(), ensure_ascii=False, indent=2))
        return 0
    plan = load_plan(_Path(a.plan))
    steps = {x.strip() for x in a.steps.split(",") if x.strip()}
    batch = a.batch or plan.get("batch") or _time.strftime("%Y%m%d")
    root = _Path(a.out) if a.out else sess.data_dir() / "inbox" / "pkulaw" / batch
    search_cfg, fetch_cfg = plan.get("search", {}), plan.get("fetch", {})
    dl_cfg = plan.get("download", {})
    runs = expand_runs(plan)
    with sess.Session(browser=a.browser) as s:
        _ensure_login(s, a.timeout, entry=plan["lib"] if plan["lib"] in sess.LIB_ENTRY else "apy")
        api = api_mod.PkulawApi(s, min_interval_s=a.interval)
        for run in runs:
            run_dir = root / "search" / run["id"].replace("/", "_")
            print(f"\n=== {run['id']}（{run['term']}｜{run.get('region','')}｜{run.get('window') or '不限窗'}）===")
            if "search" in steps:
                run_search(api, plan, run, run_dir,
                           page_size=search_cfg.get("page_size", 50),
                           max_pages=search_cfg.get("max_pages", 40),
                           limit=search_cfg.get("limit", 500),
                           order_by=search_cfg.get("order_by", ""),
                           split=plan.get("split"), dump_bodies=a.dump_body)
            if "fetch" in steps:
                fetch_run(s, run_dir, limit=fetch_cfg.get("limit", 0),
                          min_interval_s=fetch_cfg.get("min_interval_s", 2.0),
                          keep_other=fetch_cfg.get("only") != "narrative")
                if fetch_cfg.get("ingest"):
                    run_ingest(run_dir / "fetch", run_dir / "ingest",
                               harvest_date=_time.strftime("%Y-%m-%d"),
                               worklist=plan.get("worklist", ""),
                               batch=run_dir.name)
            if "download" in steps:
                from pkulaw_agent.download import download_run
                download_run(s, run_dir, root / "downloads",
                             cap=dl_cfg.get("per_run", 50),
                             min_interval_s=fetch_cfg.get("min_interval_s", 2.0),
                             manual=a.manual_download)
    print(f"\n批次目录：{root}")
    return 0


# ---- serve：长驻窗口 ----
def cmd_serve(a: argparse.Namespace) -> int:
    """一个浏览器跑完所有命令：本命令启动长驻 Chrome（CDP 端口），其它命令自动接管。"""
    prof = sess.profile_dir()
    prof.mkdir(parents=True, exist_ok=True)
    if sess.cdp_probe(a.port):
        print(f"已有 serve 在运行（127.0.0.1:{a.port}）——直接用即可；要另开一个请改 --port。")
        return 0
    exe = _find_browser(a.browser)
    if not exe:
        print(f"未找到 {a.browser} 可执行文件；检查安装或用 --browser msedge。")
        return 1
    url = sess.LIB_ENTRY.get(a.entry, sess.LIB_ENTRY["apy"])
    cmd = [exe, f"--user-data-dir={prof}", f"--remote-debugging-port={a.port}",
           "--no-first-run", "--no-default-browser-check", url]
    print(f"启动长驻窗口：{exe}")
    print(f"  profile：{prof}")
    print(f"  CDP：http://127.0.0.1:{a.port}")
    proc = subprocess.Popen(cmd)
    for _ in range(30):
        if sess.cdp_probe(a.port):
            break
        time.sleep(1)
    if not sess.cdp_probe(a.port):
        print("30 秒内 CDP 未就绪。若本机已有同 profile 的 Chrome 在跑，新进程会并入旧实例且不带调试端口"
              "——请先全部关闭，再重跑 serve。")
        return 1
    print("✅ 就绪。请在此窗口中完成登录（如未登录）。此后所有命令将自动接管此窗口，不再新开、不会闪断。")
    print("（本进程运行 = 窗口保持；Ctrl+C 结束本进程——浏览器会继续运行，可手动使用或关闭。）")
    try:
        while proc.poll() is None:
            time.sleep(3)
        print("浏览器窗口已关闭，serve 退出。")
    except KeyboardInterrupt:
        print("\nserve 已结束（浏览器保持运行；需要关闭请手动关窗）。")
    return 0


# ---- jobs：作业单 ----
def cmd_jobs(a: argparse.Namespace) -> int:
    from pkulaw_agent.jobs import jobs_from_csv, jobs_from_mcp
    if a.jobs_cmd == "from-mcp":
        stats = jobs_from_mcp(Path(a.cache), out=Path(a.out), year=a.year, law=a.law,
                              organ=a.organ)
    elif a.jobs_cmd == "from-csv":
        stats = jobs_from_csv(Path(a.csv), out=Path(a.out), year=a.year)
    else:
        print("未知子命令：jobs {from-mcp|from-csv}")
        return 1
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


# ---- run：作业流水线 ----
def cmd_run(a: argparse.Namespace) -> int:
    from pkulaw_agent.run import run_jobs
    with sess.Session(browser=a.browser, cdp_port=a.cdp_port) as s:
        _ensure_login(s, a.timeout)
        run_jobs(s, Path(a.jobs), out_dir=Path(a.out) if a.out else None,
                 cap=a.cap, dry_run=a.dry_run, resume=not a.no_resume, force=a.force,
                 min_interval=a.interval, window_spec=a.window, min_facts=a.min_facts,
                 download_format=a.download_format)
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="pkulaw_agent")
    ap.add_argument("--data-dir", help="覆盖 $JUSTILAW_DATA_DIR")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="环境自检（不联网）")

    p = sub.add_parser("login", help="稳定登录：登录成功前窗口不会关闭；成功后写 session.json")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--entry", default="apy", choices=sorted(sess.LIB_ENTRY))
    p.add_argument("--lib", default="apy", choices=sorted(api_mod.LIBS), help="用哪个库校验权限")
    p.add_argument("--timeout", type=int, default=0, help="秒；0=不限（默认等你在窗口里完成登录）")
    p.add_argument("--hold", action=argparse.BooleanOptionalAction, default=None,
                   help="登录成功后保持窗口（默认：交互终端保持；非交互 4 秒后自动关）")
    p.add_argument("--grace", type=int, default=4, help="成功后自动关窗等待秒数（非 hold 时）")
    p.add_argument("--cdp-port", type=int, default=sess.DEFAULT_CDP_PORT,
                   help="检测到 serve 长驻窗口时直接接管（0=不接管，总是自启）")

    p = sub.add_parser("recon", help="登录后捕获 XHR（脱敏），固化端点与字段")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--entry", default="apy", choices=sorted(sess.LIB_ENTRY))
    p.add_argument("--lib", default="apy", choices=sorted(api_mod.LIBS))
    p.add_argument("--tag", default="", help="批次标签，默认时间戳")
    p.add_argument("--seconds", type=int, default=0, help="自动结束秒数（0=回车结束）")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--replay", action=argparse.BooleanOptionalAction, default=True,
                   help="捕获结束后回放所捕获的检索请求以固化响应字段（默认开）")
    p.add_argument("--max-replay", type=int, default=20)

    p = sub.add_parser("cluster", help="拉取筛选维度与 id 映射")
    p.add_argument("--lib", default="apy", choices=sorted(api_mod.LIBS))
    p.add_argument("--dim", default=None, help="维度名（如 CategoryNew；缺省探测全部）")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--max-chars", type=int, default=2500)

    p = sub.add_parser("call", help="任意 API 直调（agent 探索用）")
    p.add_argument("--path", required=True)
    p.add_argument("--body", default="", help="JSON 字符串或 @文件")
    p.add_argument("--save", default="")
    p.add_argument("--entry", default="apy", choices=sorted(sess.LIB_ENTRY))
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--max-chars", type=int, default=4000)

    p = sub.add_parser("search", help="检索（分页/饱和拆分）→ results.jsonl")
    p.add_argument("--plan", default="", help="作业单 JSON；缺省用 --lib/--term 单任务")
    p.add_argument("--lib", default="apy", choices=sorted(api_mod.LIBS))
    p.add_argument("--term", default="")
    p.add_argument("--region", default="")
    p.add_argument("--window", default="", help="时间窗 A:B（YYYY-MM-DD:YYYY-MM-DD）")
    p.add_argument("--run-id", default="", help="只跑匹配的 run id")
    p.add_argument("--batch", default="")
    p.add_argument("--out", default="")
    p.add_argument("--page-size", type=int, default=0)
    p.add_argument("--max-pages", type=int, default=0)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--order-by", default="")
    p.add_argument("--interval", type=float, default=1.5)
    p.add_argument("--dump-body", action="store_true", help="打印每页请求体（联调第一轮用）")
    p.add_argument("--template", action="store_true", help="打印作业单模板后退出")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--timeout", type=int, default=600)

    p = sub.add_parser("fetch", help="零配额抓正文 → .txt + 形态预探（可接解析链）")
    p.add_argument("--run", required=True, help="search 产出的 run 目录（含 results.jsonl）")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--min-interval", type=float, default=2.0)
    p.add_argument("--only-narrative", action="store_true",
                   help="只保留识别为叙述式的正文文件（其余仍记录预探结论）")
    p.add_argument("--ingest", action="store_true", help="抓完直接走 pkulaw_ingest 解析链")
    p.add_argument("--ingest-out", default="")
    p.add_argument("--harvest-date", default="")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--timeout", type=int, default=600)

    p = sub.add_parser("download", help="下载文件（逐条/结果页；可人工兜底）")
    p.add_argument("--run", default="", help="对 search 结果逐条开详情页下载")
    p.add_argument("--url", default="", help="对已有结果页执行勾选→下载")
    p.add_argument("--ui-search", action="store_true", help="先在本机库页检索再下载")
    p.add_argument("--term", default="")
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--cap", type=int, default=50, help="本次最多下载条数（配额红线）")
    p.add_argument("--format", default="auto", choices=["auto", "word", "pdf"],
                   help="下载格式：auto=Word 优先回退 PDF（默认）")
    p.add_argument("--manual", action="store_true", help="自动失败时转人工点一下，文件自动收")
    p.add_argument("--lib", default="apy", choices=sorted(api_mod.LIBS))
    p.add_argument("--batch", default="")
    p.add_argument("--out", default="")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--timeout", type=int, default=600)

    p = sub.add_parser("harvest", help="一条命令：search→fetch[→download]")
    p.add_argument("--plan", default="")
    p.add_argument("--template", action="store_true")
    p.add_argument("--steps", default="search,fetch")
    p.add_argument("--batch", default="")
    p.add_argument("--out", default="")
    p.add_argument("--manual-download", action="store_true")
    p.add_argument("--interval", type=float, default=1.5)
    p.add_argument("--dump-body", action="store_true")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--timeout", type=int, default=600)

    p = sub.add_parser("serve", help="长驻窗口：一个浏览器跑完所有命令（CDP 接管，不闪断）")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--entry", default="apy", choices=sorted(sess.LIB_ENTRY))
    p.add_argument("--port", type=int, default=sess.DEFAULT_CDP_PORT)

    p = sub.add_parser("jobs", help="作业单：MCP 缓存 / 清洗清单 → jobs.jsonl")
    jsub = p.add_subparsers(dest="jobs_cmd", required=True)
    p = jsub.add_parser("from-mcp", help="读 MCP 调用层缓存生成作业单（0 积分，缓存免费）")
    p.add_argument("--cache", required=True,
                   help="如 $DATA/engine/pkulaw_mcp/cache/pkulaw-enforcement-doc_mcp")
    p.add_argument("--out", required=True)
    p.add_argument("--year", default="", help="按处罚日期年份过滤，如 2026")
    p.add_argument("--law", default="", choices=["", "新法"], help="law=新法 只留 2025修订/第82条")
    p.add_argument("--organ", default="", help="机关名包含过滤")
    p = jsub.add_parser("from-csv", help="读清洗清单（含「原文链接」列）生成作业单")
    p.add_argument("--csv", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--year", default="")

    p = sub.add_parser("run", help="跑作业：打开→抓正文→六校验→（通过才）限额下载→报告")
    p.add_argument("--jobs", required=True, help="jobs.jsonl")
    p.add_argument("--out", default="", help="输出目录（缺省=作业单所在目录）")
    p.add_argument("--cap", type=int, default=30, help="本次最多下载件数（配额红线）")
    p.add_argument("--dry-run", action="store_true", help="只校验不下载")
    p.add_argument("--download-format", default="auto", choices=["auto", "word", "pdf"],
                   help="下载格式：auto=Word 优先、失败回退 PDF（默认）；word=只点下载WORD；pdf=只点下载PDF")
    p.add_argument("--no-resume", action="store_true", help="不跳过已完成件（默认跳过）")
    p.add_argument("--force", action="store_true", help="忽略历史状态全部重做")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--window", default="", help="年份窗，如 2026 或 2025:2026（处罚日期与正文年份）")
    p.add_argument("--min-facts", type=int, default=50, help="叙述式事实段最小字数")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--cdp-port", type=int, default=sess.DEFAULT_CDP_PORT)

    a = ap.parse_args(argv)
    if a.data_dir:
        os.environ["JUSTILAW_DATA_DIR"] = a.data_dir
    handler = {"doctor": cmd_doctor, "login": cmd_login, "recon": cmd_recon,
               "cluster": cmd_cluster, "call": cmd_call,
               "search": cmd_search, "fetch": cmd_fetch,
               "download": cmd_download, "harvest": cmd_harvest,
               "serve": cmd_serve, "jobs": cmd_jobs, "run": cmd_run}[a.cmd]
    try:
        return handler(a)
    except sess.LoginRequired as exc:
        print(f"\n[需登录] {exc}")
        return 2
    except sess.SecurityChallenge as exc:
        print(f"\n[安全验证] {exc}")
        return 3
    except PermissionError as exc:
        print(f"\n[登录失效] {exc}（重跑 login）")
        return 2
    except KeyboardInterrupt:
        print("\n已中断（进度已落盘，可重跑续做）")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

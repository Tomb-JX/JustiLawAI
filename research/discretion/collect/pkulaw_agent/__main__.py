"""法宝作业台命令行入口（M0/M1）。

用法（任选其一，建议直接运行本文件）：
  python research/discretion/collect/pkulaw_agent/__main__.py doctor
  python research/discretion/collect/pkulaw_agent/__main__.py login [--timeout 600]
  python research/discretion/collect/pkulaw_agent/__main__.py recon [--tag 20261016] [--seconds 0]
  python research/discretion/collect/pkulaw_agent/__main__.py cluster --lib apy [--dim CategoryNew]
  python research/discretion/collect/pkulaw_agent/__main__.py call --path /searchingapi/adv/list/apy \
      --body '{"pageIndex":0,"pageSize":5}'

红线（design §3）：不绕验证码/风控；单账号人类节奏；凭据与 profile 不进仓库。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    return 0


# ---- login ----
def cmd_login(a: argparse.Namespace) -> int:
    with sess.Session(browser=a.browser) as s:
        s.open_entry(a.entry)
        tok = s.token()
        if tok:
            print(f"检测到已有登录态：{sess.mask_token(tok)}  到期约 {sess.jwt_exp_hint(tok) or '未知'}")
        else:
            print("未检测到登录态。请在打开的浏览器窗口中完成登录（账号密码 / 微信扫码 / 验证码均可）。")
        tok = tok or s.wait_for_login(a.timeout)
        api = api_mod.PkulawApi(s)
        try:
            api.verify_login(a.lib)
        except PermissionError:
            print("token 已存在但校验失败（可能已过期）——请在窗口中重新登录，继续等待……")
            s.wait_for_login(a.timeout, poll_s=3)
            api.verify_login(a.lib)
        print(f"登录成功：{sess.mask_token(tok)}  到期约 {sess.jwt_exp_hint(tok) or '未知'}")
        print(f"登录态已保存在 profile：{sess.profile_dir()}")
        print("提示：保持账号单会话使用；出现安全验证页时按页面提示人工完成即可（工具不绕过）。")
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


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="pkulaw_agent")
    ap.add_argument("--data-dir", help="覆盖 $JUSTILAW_DATA_DIR")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="环境自检（不联网）")

    p = sub.add_parser("login", help="打开真窗口手动登录并固化 profile")
    p.add_argument("--browser", default="chrome", choices=sess.BROWSERS)
    p.add_argument("--entry", default="apy", choices=sorted(sess.LIB_ENTRY))
    p.add_argument("--lib", default="apy", choices=sorted(api_mod.LIBS), help="用哪个库校验权限")
    p.add_argument("--timeout", type=int, default=600)

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

    a = ap.parse_args(argv)
    if a.data_dir:
        os.environ["JUSTILAW_DATA_DIR"] = a.data_dir
    handler = {"doctor": cmd_doctor, "login": cmd_login, "recon": cmd_recon,
               "cluster": cmd_cluster, "call": cmd_call}[a.cmd]
    try:
        return handler(a)
    except sess.LoginRequired as exc:
        print(f"\n[需登录] {exc}")
        return 2
    except sess.SecurityChallenge as exc:
        print(f"\n[安全验证] {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

"""网页抓取版（零下载权限时用）：CDP 复用 9222 常驻 Chrome，调用现有 fetch_run。

用法：
    python -m pkulaw_agent.fetch_cdp --run-dir <dir含results.jsonl> [--out-dir <dir>] [--limit N]

复用 fetch.py 全部逻辑（#divFullText 正文、.fields 元数据、表格、coverage sidecar）。
红线：≥1.5s/请求、被安全验证拦即停不绕过。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pkulaw_agent.fetch import fetch_run
from pkulaw_agent.session import data_dir


class CDPPage:
    """最小 page 代理：转发 fetch_run/fetch_one 用到的方法。"""

    def __init__(self, page) -> None:
        self._p = page

    def goto(self, *a, **kw):
        return self._p.goto(*a, **kw)

    def evaluate(self, *a, **kw):
        return self._p.evaluate(*a, **kw)

    def wait_for_timeout(self, *a, **kw):
        return self._p.wait_for_timeout(*a, **kw)

    def title(self):
        return self._p.title()

    @property
    def url(self):
        return self._p.url

    @property
    def locator(self):
        return self._p.locator


class CDPFetchSession:
    """最小 session 代理：fetch_run 需要 session.page 与 session._check_challenge。"""

    def __init__(self, page) -> None:
        self.page = CDPPage(page)

    def _check_challenge(self) -> None:
        try:
            t = self.page.title()
        except Exception:  # noqa: BLE001
            return
        if "安全验证" in t or "访问安全" in t:
            raise RuntimeError(
                "命中 EdgeOne 安全验证页——红线：不绕过。请在浏览器窗口人工完成后重跑。")


def main():
    ap = argparse.ArgumentParser(description="L4/无下载权限时网页抓取（CDP）")
    ap.add_argument("--run-dir", required=True, help="含 results.jsonl 的目录")
    ap.add_argument("--out-dir", default="", help="抓取输出目录（默认 run-dir/fetch）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--only-narrative", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    if not (run_dir / "results.jsonl").exists():
        print(f"{run_dir} 下没有 results.jsonl")
        return 1
    out_dir = Path(args.out_dir) if args.out_dir else None

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.new_page()  # 单页复用
    session = CDPFetchSession(page)

    try:
        fetch_run(session, run_dir, out_dir=out_dir, limit=args.limit,
                  min_interval_s=args.interval, keep_other=not args.only_narrative)
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        pw.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
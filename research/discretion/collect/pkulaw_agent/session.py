"""法宝可见浏览器会话（M0）：真窗口 Chrome + 持久化 profile + 同源 API 调用。

实测依据（docs/04-plan/pkulaw-agent-design.md §2.1）：
- headless 会被 EdgeOne 拦（567"访问安全验证"）；真窗口正常加载 → 必须 headed；
- 登录态 = localStorage.access_token（首页也可从隐藏 input #AccessToken 读到）；
- 所有 API 在页面上下文 fetch，自动携带 cookie 与防护通行证。

红线：不做指纹伪装、不绕验证码/挑战；被拦即暂停并提示人工处理。
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

BASE = "https://www.pkulaw.com"
LIB_ENTRY = {
    "apy": f"{BASE}/penalty?way=topGuid",   # 行政执法库
    "pfnl": f"{BASE}/case?way=topGuid",     # 司法案例库
    "chl": f"{BASE}/",                      # 法律法规库
}
DEFAULT_DATA_DIR = r"D:/02_Dev/Data/justilaw-research"
BROWSERS = ("chrome", "msedge")

_TOKEN_JS = ("() => (localStorage.getItem('access_token') || "
             "(document.getElementById('AccessToken') || {}).value || '')")


def data_dir() -> Path:
    return Path(os.environ.get("JUSTILAW_DATA_DIR", DEFAULT_DATA_DIR))


def profile_dir() -> Path:
    return data_dir() / "browser-profile" / "pkulaw"


class LoginRequired(RuntimeError):
    """未检测到登录态。"""


class SecurityChallenge(RuntimeError):
    """EdgeOne 安全验证页拦住了当前会话。红线：不绕过，等待人工或稍后重试。"""


def mask_token(token: str) -> str:
    token = token or ""
    return token[:10] + "…" + token[-4:] if len(token) > 18 else "***"


def jwt_exp_hint(token: str) -> str:
    """从 JWT 解出到期时间（仅用于诊断展示，失败返回空串）。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = int(data.get("exp", 0))
        if exp:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))
    except Exception:  # noqa: BLE001 —— 诊断用途，任何解析失败都静默
        pass
    return ""


class Session:
    """真窗口 Chrome + 持久 profile 的法宝会话。上下文管理器用法：

        with Session() as s:
            s.open_entry("apy")
            token = s.token() or s.wait_for_login(600)
    """

    def __init__(self, browser: str = "chrome", data_dir_: Path | None = None,
                 slow_extra_ms: int = 0) -> None:
        if browser not in BROWSERS:
            raise ValueError(f"browser 只能是 {BROWSERS}")
        self.browser = browser
        self.root = data_dir_ or data_dir()
        self.slow_extra_ms = slow_extra_ms
        self._pw = None
        self._ctx = None
        self._page = None

    # ---- 生命周期 ----
    def __enter__(self) -> "Session":
        from playwright.sync_api import sync_playwright

        prof = self.root / "browser-profile" / "pkulaw"
        prof.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(prof),
                channel=self.browser,
                headless=False,  # 必须可见：headless 会被拦（实测）
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                args=["--no-first-run", "--no-default-browser-check"],
                accept_downloads=True,
            )
        except Exception as exc:  # noqa: BLE001
            self._pw.stop()
            raise RuntimeError(
                f"浏览器启动失败（{self.browser}）：{exc}\n"
                f"提示：若上次运行异常退出，检查是否还有残留的 Chrome 进程占用 profile：{prof}"
            ) from exc
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc: Any) -> None:
        for closer in (self._ctx, self._pw):
            try:
                if closer is not None:
                    closer.close() if closer is self._ctx else closer.stop()
            except Exception:  # noqa: BLE001
                pass

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("会话未启动（先用 with Session()）")
        return self._page

    # ---- 导航与登录态 ----
    def _check_challenge(self) -> None:
        title = ""
        try:
            title = self.page.title()
        except Exception:  # noqa: BLE001
            return
        if "安全验证" in title or "访问安全" in title:
            raise SecurityChallenge(
                "当前显示 EdgeOne 安全验证页。请在该浏览器窗口内按页面提示人工完成验证，"
                "然后重跑本命令；工具不会、也不应绕过验证。"
            )

    def open_entry(self, lib: str = "apy", settle_s: int = 8) -> None:
        """打开发令库入口页并等待 SPA 就绪（含防护脚本执行）。"""
        url = LIB_ENTRY.get(lib)
        if not url:
            raise ValueError(f"未知库：{lib}（可选 {sorted(LIB_ENTRY)}）")
        self.page.goto(url, wait_until="commit", timeout=120_000)
        for _ in range(settle_s * 2):
            self.page.wait_for_timeout(500)
        self._check_challenge()

    def token(self) -> str:
        try:
            return (self.page.evaluate(_TOKEN_JS) or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def wait_for_login(self, timeout_s: int = 600, poll_s: int = 2) -> str:
        """轮询登录态；期间用户可在可见窗口中手动登录（账号密码/微信/验证码均可）。

        返回 access_token。超时抛 LoginRequired。轮询用 page.wait_for_timeout 以驱动
        Playwright 事件循环（time.sleep 会挂起事件分发）。
        """
        waited = 0.0
        last_tip = 0.0
        while waited < timeout_s:
            tok = self.token()
            if tok:
                return tok
            self.page.wait_for_timeout(poll_s * 1000)
            waited += poll_s
            if waited - last_tip >= 15:
                last_tip = waited
                print(f"  等待登录中…（{int(waited)}s / {timeout_s}s；请在浏览器窗口中完成登录）")
        raise LoginRequired(
            f"{timeout_s}s 内未检测到登录态。请在窗口内完成登录后重试；"
            "若窗口已关闭，重跑 login 命令。"
        )

    # ---- API ----
    def api_post(self, path: str, body: dict | None = None,
                 timeout_ms: int = 45_000, token: str | None = None) -> dict:
        """在页面上下文 POST JSON。返回 {"status": int, "text": str} 或 {"status": -1, "error": str}。"""
        tok = token if token is not None else self.token()
        if not tok:
            raise LoginRequired("无 access_token：先 login")
        js = """async ([path, body, token, timeoutMs]) => {
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), timeoutMs);
            try {
                const resp = await fetch(path, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'Authorization': token},
                    body: JSON.stringify(body || {}),
                    signal: ctrl.signal,
                });
                const text = await resp.text();
                return {status: resp.status, text};
            } catch (e) { return {status: -1, error: String(e)}; }
            finally { clearTimeout(timer); }
        }"""
        out = self.page.evaluate(js, [path, body or {}, tok, timeout_ms])
        if self.slow_extra_ms:
            self.page.wait_for_timeout(self.slow_extra_ms)
        if out.get("status") == -1:
            raise RuntimeError(f"API 请求失败：{out.get('error')}")
        return out

    def api_get_html(self, url: str, settle_s: int = 3) -> str:
        """导航到详情页并返回 HTML（SPA 渲染后）。用于 M2 的 fetch/probe。"""
        self.page.goto(url, wait_until="commit", timeout=120_000)
        for _ in range(settle_s * 2):
            self.page.wait_for_timeout(500)
        self._check_challenge()
        return self.page.content()

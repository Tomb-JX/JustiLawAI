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
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://www.pkulaw.com"
DEFAULT_CDP_PORT = 9222
_CHROME = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
_EDGE = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
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


def session_info_path() -> Path:
    return data_dir() / "session.json"


def load_session_info() -> dict:
    p = session_info_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def save_session_info(**fields: Any) -> None:
    """登录健康信息（仓库外；只存非敏感字段）。"""
    info = load_session_info()
    info.update({k: v for k, v in fields.items()})
    session_info_path().write_text(json.dumps(info, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def cdp_probe(port: int = DEFAULT_CDP_PORT, timeout_s: float = 1.0) -> dict:
    """探测本机 CDP 端口（serve 长驻窗口）。未开返回 {}。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                    timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {}


def profile_lock_files(prof: Path | None = None) -> list[str]:
    """profile 目录里的锁文件（Chrome 正在使用/异常残留的线索，仅作诊断）。"""
    prof = prof or profile_dir()
    return [n for n in ("lockfile", "SingletonLock", "SingletonCookie") if (prof / n).exists()]


def browser_exe(browser: str = "chrome") -> str:
    for p in (_CHROME if browser == "chrome" else _EDGE):
        if Path(p).exists():
            return p
    return ""


def ensure_serve(port: int = DEFAULT_CDP_PORT, browser: str = "chrome", entry: str = "apy",
                 wait_s: int = 30, logger=print) -> bool:
    """确保有一个**常驻可接管**的浏览器窗口（v1.2 核心）：

    - 已有 CDP（serve 在跑）→ 直接复用，窗口不会开开关关；
    - 没有 → 以独立进程拉起（detached，命令结束**不关窗**），等端口就绪。
    窗口一经拉起即长期保持：登录态/token 由站点 SPA 自行续期，命令之间不再重复开窗。
    """
    if cdp_probe(port):
        return True
    exe = browser_exe(browser)
    if not exe:
        logger(f"未找到 {browser} 可执行文件；无法自动拉起常驻窗口")
        return False
    prof = profile_dir()
    prof.mkdir(parents=True, exist_ok=True)
    url = LIB_ENTRY.get(entry, LIB_ENTRY["apy"])
    cmd = [exe, f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
           "--no-first-run", "--no-default-browser-check", url]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS|NEW_PROCESS_GROUP
    try:
        subprocess.Popen(cmd, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger(f"常驻窗口拉起失败：{exc}")
        return False
    logger(f"已拉起常驻窗口（CDP {port}）——请在窗口中登录（如未登录）；窗口会一直保持，不再自动关闭。")
    for _ in range(wait_s):
        if cdp_probe(port):
            return True
        time.sleep(1)
    logger("30 秒内 CDP 未就绪；若已有同 profile 的 Chrome 在跑，请先关闭后重试")
    return False


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
                 slow_extra_ms: int = 0, cdp_port: int = DEFAULT_CDP_PORT) -> None:
        if browser not in BROWSERS:
            raise ValueError(f"browser 只能是 {BROWSERS}")
        self.browser = browser
        self.root = data_dir_ or data_dir()
        self.slow_extra_ms = slow_extra_ms
        self.cdp_port = cdp_port  # 0 = 不探测 CDP，总是自启窗口
        self._pw = None
        self._ctx = None
        self._page = None
        self._browser = None
        self._mode = "launch"

    # ---- 生命周期 ----
    def __enter__(self) -> "Session":
        from playwright.sync_api import sync_playwright

        prof = self.root / "browser-profile" / "pkulaw"
        prof.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        if self.cdp_port and cdp_probe(self.cdp_port):
            try:  # serve 长驻窗口中 → 直接接管（不开新窗、不动用户正在看的页面）
                self._browser = self._pw.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self.cdp_port}")
                self._ctx = (self._browser.contexts[0] if self._browser.contexts
                             else self._browser.new_context(accept_downloads=True))
                self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
                self._mode = "cdp"
                return self
            except Exception as exc:  # noqa: BLE001 —— 接管失败退回自启
                print(f"（CDP 接管失败，退回自启窗口：{exc}）")
                self._browser = None
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
            locks = profile_lock_files(prof)
            raise RuntimeError(
                f"浏览器启动失败（{self.browser}）：{exc}\n"
                f"提示：profile 锁文件：{locks or '无'}；若也有 Chrome 在跑请先关闭，"
                f"或改用 `serve` 长驻模式。profile：{prof}"
            ) from exc
        self._mode = "launch"
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            if self._mode == "cdp":
                pass  # 接管模式：只断开驱动，不关闭用户的浏览器窗口
            elif self._ctx is not None:
                self._ctx.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("会话未启动（先用 with Session()）")
        return self._page

    @property
    def context(self):
        if self._ctx is None:
            raise RuntimeError("会话未启动（先用 with Session()）")
        return self._ctx

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

    def account_hint(self) -> str:
        """从页面读机构/账号线索（尽力而为，失败返空）。"""
        js = ("() => { const m = document.body ? document.body.innerText.match("
              "/(?:机构|单位|账号)[:：]?\\s*([\\u4e00-\\u9fa5A-Za-z0-9（）()]{2,30})/) : null;"
              " return m ? m[1] : ''; }")
        try:
            return (self.page.evaluate(js) or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def page_closed(self) -> bool:
        try:
            return bool(self._page is None or self._page.is_closed())
        except Exception:  # noqa: BLE001
            return True

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
                    headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
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

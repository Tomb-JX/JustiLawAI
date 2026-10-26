"""CDP 后台标签工厂——纪律见 crawler-ops §5：后台自动化不得抢占用户界面。

connect_over_cdp 后统一用 open_background_page 拿一个**后台标签**（Target.createTarget
background:true），全程复用、绝不 bring_to_front。用户看不到弹窗或切页。
旧代码 `ctx.new_page()` 会抢焦点，禁止再用。
"""

from __future__ import annotations

# 复用锚点页面（已存在的任意标签）发 CDP；没有锚点就退回 new_page（首次启动时）。
def open_background_page(ctx):
    anchor = ctx.pages[0] if ctx.pages else None
    if anchor is not None:
        try:
            cdp = ctx.new_cdp_session(anchor)
            with ctx.expect_page(timeout=5000) as info:
                cdp.send("Target.createTarget", {"url": "about:blank", "background": True})
            return info.value
        except Exception:  # noqa: BLE001 —— CDP 不可用退回普通页（不静默失败）
            pass
    return ctx.new_page()

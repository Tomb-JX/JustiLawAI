"""法宝 API 封装（M1 起）：同源调用、响应判定、筛选维度拉取。

端点族（实测，见设计 §2.3）：
  POST /searchingapi/adv/list/{lib}    检索（lib: apy=行政执法 / pfnl=司法案例 / chl=法规）
  POST /searchingapi/adv/cluster/{lib} 筛选维度与 id 映射（body: {"dimensionId": ...}）
判定函数与请求体构造是纯函数，便于单测；调用部分委托 Session.api_post。
"""

from __future__ import annotations

import json
from typing import Any

LIBS = {"apy": "行政执法", "pfnl": "司法案例", "chl": "法律法规"}
PAGE_SIZE_DEFAULT = 50  # 与网页导出页一致（实测一次导出=一页 50 篇）


# ---- 纯函数：响应判定（错误分类沿用存量项目实测的判据） ----
def safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def is_token_error(data: Any) -> bool:
    return isinstance(data, dict) and str(data.get("code", "")) == "1" and \
        "token" in str(data.get("message", "")).lower()


def is_security_block(data: Any) -> bool:
    return isinstance(data, dict) and data.get("code") == "SecurityProtection"


def is_captcha(data: Any) -> bool:
    err = data.get("error", {}) if isinstance(data, dict) else {}
    return isinstance(err, dict) and "captcha" in str(err.get("code", "")).lower()


def is_ok_list(data: Any) -> bool:
    return isinstance(data, dict) and ("total" in data or "data" in data)


def build_search_body(*, page_index: int = 0, page_size: int = PAGE_SIZE_DEFAULT,
                      order_by: str = "", field_nodes: list[dict] | None = None,
                      cluster_filters: dict | None = None,
                      group_by: dict | None = None) -> dict:
    """检索请求体骨架（字段节点形态与存量项目一致；执法库字段名以 recon 捕获为准）。"""
    return {
        "orderbyExpression": order_by,
        "pageIndex": page_index,
        "pageSize": page_size,
        "fieldNodes": field_nodes or [],
        "clusterFilters": cluster_filters or {},
        "groupBy": group_by or {},
    }


def build_cluster_body(dimension_id: str | None) -> dict:
    return {"dimensionId": dimension_id} if dimension_id else {}


# ---- 调用（依赖 Session） ----
class PkulawApi:
    def __init__(self, session, min_interval_s: float = 1.5) -> None:
        self.s = session
        self.min_interval_s = min_interval_s
        self._last_call = 0.0

    def _pace(self) -> None:
        import random
        import time
        now = time.monotonic()
        wait = self.min_interval_s + random.uniform(0, 1.0) - (now - self._last_call)
        if wait > 0:
            self.s.page.wait_for_timeout(int(wait * 1000))
        self._last_call = time.monotonic()

    def call(self, path: str, body: dict | None = None) -> Any:
        """POST 并返回解析后的 JSON；token 失效抛 PermissionError，风控抛 RuntimeError。"""
        self._pace()
        out = self.s.api_post(path, body)
        data = safe_json(out["text"])
        if data is None:
            raise RuntimeError(f"非 JSON 响应（status={out['status']}）：{out['text'][:200]}")
        if is_token_error(data):
            raise PermissionError("token 失效：请重跑 login 重新登录")
        if is_security_block(data) or is_captcha(data):
            raise RuntimeError("触发风控（SecurityProtection/captcha）：按红线立即暂停，等待人工处理后重试")
        return data

    def search(self, lib: str, body: dict) -> Any:
        if lib not in LIBS:
            raise ValueError(f"lib 必须是 {sorted(LIBS)}")
        return self.call(f"/searchingapi/adv/list/{lib}", body)

    def cluster(self, lib: str, dimension_id: str | None = None) -> Any:
        return self.call(f"/searchingapi/adv/cluster/{lib}", build_cluster_body(dimension_id))

    def verify_login(self, lib: str = "apy") -> bool:
        """用一次最小检索确认登录态与库权限。"""
        data = self.call(f"/searchingapi/adv/list/{lib}",
                         build_search_body(page_size=1))
        return is_ok_list(data)

"""侦察捕获（M1）：登录后记录 XHR 端点族、请求体形态与响应字段名（脱敏）。

用途：一次人工操作（检索 / 打开详情 / 点下载）即可固化执法库的检索字段、详情路由与下载端点，
供 M2 的 search/probe/fetch 使用。捕获在**登录之后**才开始；敏感键值一律不落盘。

纯函数（should_record/record_kind/scrub_keys/shrink_json）可单测；Recorder 负责挂事件与落盘。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

# 登录/鉴权/静态资源路径：永不记录（登录流量绝不入档）
SKIP_PATH = re.compile(
    r"(newlogin|ssologinurl|VerificationCode|getCode|usercenter|/gateway|/login|"
    r"oauth|/sso|logout|/auth/realms|CheckKcIsLoginPage|kc-sessions|/help/|"
    r"/App_Data|/Scripts|/Content/|\.css|\.js($|\?)|\.png|\.jpg|\.svg|\.ico|\.woff)",
    re.I,
)
# 业务 API 前缀（我们的目标）
API_PATH = re.compile(r"/(searchingapi|api|ruoyi-api|searchapi)/", re.I)
# 维度字典（筛选 id 映射，无个人信息）：响应全量留档
KEEP_FULL = re.compile(r"/searchingapi/adv/cluster/", re.I)
# 可能承载凭据的键：值一律替换
SENSITIVE_KEY = re.compile(
    r"(pass|pwd|token|secret|captcha|verif|sms|mobile|phone|ticket|signature|authorization)", re.I
)

_VALUE_SUMMARY_MAX = 60


def should_record(resource_type: str, url: str) -> bool:
    if SKIP_PATH.search(url):
        return False
    return resource_type in ("xhr", "fetch", "document")


def record_kind(resource_type: str, url: str) -> str:
    """→ "api"（业务 API，记录体/字段）、"nav"（页面导航，只记路径）、""（不记）。"""
    if not should_record(resource_type, url):
        return ""
    if API_PATH.search(url) or KEEP_FULL.search(url):
        return "api"
    if resource_type == "document":
        return "nav"
    return ""


def _path_only(url: str, with_query_keys: bool = True) -> str:
    """只保留 path；查询串仅保留键名（防意外携带个人参数）。"""
    no_scheme = re.sub(r"^https?://[^/]+", "", url)
    if "?" not in no_scheme:
        return no_scheme
    path, query = no_scheme.split("?", 1)
    if not with_query_keys:
        return path
    keys = sorted({kv.split("=", 1)[0] for kv in query.split("&") if kv})
    return f"{path}?[{','.join(keys)}]"


def scrub_keys(obj: Any, depth: int = 4, max_items: int = 3) -> Any:
    """递归保留结构、脱敏敏感键值；长字符串截断；列表只取前 max_items 个样本。"""
    if depth < 0:
        return "…"
    if isinstance(obj, dict):
        out = {}
        for k, v in list(obj.items())[:40]:
            out[k] = "***" if SENSITIVE_KEY.search(str(k)) else scrub_keys(v, depth - 1, max_items)
        return out
    if isinstance(obj, list):
        return [scrub_keys(v, depth - 1, max_items) for v in obj[:max_items]] + (
            [f"…(+{len(obj) - max_items})"] if len(obj) > max_items else []
        )
    if isinstance(obj, str):
        return obj if len(obj) <= _VALUE_SUMMARY_MAX else obj[:_VALUE_SUMMARY_MAX] + "…"
    return obj


def shrink_json(obj: Any) -> dict:
    """响应只留"字段名 + 规模"：顶层键、首条样本键、总数。"""
    info: dict[str, Any] = {"_keys": []}
    if isinstance(obj, dict):
        info["_keys"] = sorted(obj.keys())[:40]
        for k in ("total", "Total", "count", "totalCount"):
            if k in obj and isinstance(obj[k], (int, str)):
                info["_total"] = obj[k]
                break
        for k, v in obj.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                info["_list_key"] = k
                info["_item_keys"] = sorted(v[0].keys())[:60]
                info["_list_len"] = len(v)
                break
            if isinstance(v, dict) and v:
                info["_dict_key"] = k
                info["_dict_keys"] = sorted(v.keys())[:40]
                break
    elif isinstance(obj, list):
        info["_keys"] = ["<list>"]
        info["_list_len"] = len(obj)
        if obj and isinstance(obj[0], dict):
            info["_item_keys"] = sorted(obj[0].keys())[:60]
    return info


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def collect_replays(jsonl_path: Path, limit: int = 20) -> list[dict]:
    """从 recon JSONL 提取可回放的 API 请求（去重，POST+JSON 体）。

    背景：响应事件回调里读响应体存在竞态（CDP 偶报 No resource with given identifier），
    因此"响应字段名"不依赖事件捕获，而用同一路径的页面内 fetch 回放取得（确定性）。
    """
    seen: set[str] = set()
    out: list[dict] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if e.get("kind") != "api" or e.get("method") != "POST" or not isinstance(e.get("req"), dict):
            continue
        if any(k.startswith("_") for k in e["req"]):  # 非 JSON 体（_raw_len）
            continue
        key = e["path"] + "|" + json.dumps(e["req"], sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": e["path"], "body": e["req"]})
        if len(out) >= limit:
            break
    return out


class Recorder:
    """挂在 Session.page 上的网络记录器。用法：

        rec = Recorder(session, tag="20261016")
        rec.start()
        ... 用户在窗口中做 3 个动作 ...
        rec.stop()   # 落 recon-<tag>.jsonl 与 summary
    """

    def __init__(self, session, tag: str = "") -> None:
        self.session = session
        self.tag = tag or time.strftime("%Y%m%d-%H%M%S")
        self.out_dir = session.root / "recon"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.out_path = self.out_dir / f"recon-{self.tag}.jsonl"
        self.counts: dict[str, int] = {}
        self._fh = None

    # ---- 事件处理 ----
    def _on_response(self, response) -> None:  # noqa: ANN001 —— Playwright 对象
        try:
            req = response.request
            kind = record_kind(req.resource_type, req.url)
            if not kind:
                return
            entry: dict[str, Any] = {
                "ts": time.strftime("%H:%M:%S"),
                "kind": kind,
                "method": req.method,
                "path": _path_only(req.url, with_query_keys=(kind == "api")),
                "status": response.status,
            }
            if kind == "api":
                try:
                    ctype = (response.header_value("content-type") or "").lower()
                except Exception:  # noqa: BLE001
                    ctype = ""
                entry["ctype"] = ctype.split(";")[0]
                body = req.post_data
                if body:
                    data = _try_json(body)
                    entry["req"] = scrub_keys(data) if data is not None else {"_raw_len": len(body)}
                if "json" in ctype:
                    try:
                        text = response.text()
                    except Exception as exc:  # noqa: BLE001 —— 少数响应体不可读，记下原因即可
                        text = ""
                        entry["_resp_err"] = f"{type(exc).__name__}: {str(exc)[:80]}"
                    data = _try_json(text) if text else None
                    if data is not None:
                        entry["resp"] = (scrub_keys(data) if KEEP_FULL.search(req.url)
                                         else shrink_json(data))
                        entry["resp_len"] = len(text)
            self._write(entry)
            key = f"{entry['method']} {entry['path']} {entry['status']}"
            self.counts[key] = self.counts.get(key, 0) + 1
            print(f"  [recon] {key}" + (f" ({entry.get('ctype','')})" if kind == "api" else ""))
        except Exception as exc:  # noqa: BLE001 —— 记录器绝不拖垮会话
            print(f"  [recon] 记录失败（忽略）：{exc}")

    def _write(self, entry: dict) -> None:
        if self._fh is None:
            self._fh = self.out_path.open("a", encoding="utf-8")
        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()

    # ---- 生命周期 ----
    def start(self) -> None:
        self.session.page.on("response", self._on_response)
        print(f"  记录开始 → {self.out_path}")

    def stop(self) -> Path:
        try:
            self.session.page.remove_listener("response", self._on_response)
        except Exception:  # noqa: BLE001
            pass
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        summary = self.out_dir / f"summary-{self.tag}.json"
        summary.write_text(json.dumps(self.counts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  记录结束：{len(self.counts)} 类请求；摘要 → {summary}")
        return self.out_path

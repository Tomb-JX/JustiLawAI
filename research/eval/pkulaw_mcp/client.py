"""MCP（Streamable HTTP）传输、会话与计费控制。

一次 tools/call 的流程：
  1. 用 (服务, 工具, 规范化参数) 算缓存键；命中则直接返回，记 0 分；
  2. 未命中：检查本次运行的预算，超出就在发请求之前报错；
  3. 发请求（必要时先 initialize 建立会话），解析 JSON 或 SSE；
  4. isError 为真时报错（错误信息不含令牌），否则写缓存、记台账、累计花费。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

GATEWAY = "https://apim-gateway.pkulaw.com"
DATA_DIR = Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research")) / "engine" / "pkulaw_mcp"
LEDGER_FIELDS = ["time", "workstream", "service", "tool", "arguments", "points", "cache_hit", "ok", "note"]

# transport(url, headers, body) -> (status, response_headers, body)
Transport = Callable[[str, dict, bytes], tuple[int, dict, bytes]]


class PkulawError(RuntimeError):
    pass


class BudgetExceeded(PkulawError):
    pass


def find_authorization() -> str:
    """令牌查找顺序：环境变量 → 官方 CLI 配置 → 数据链路的 ZCode 配置。"""
    env = os.environ.get("PKULAW_MCP_AUTHORIZATION")
    if env:
        return env
    official = Path.home() / ".pkulaw" / "mcp" / "config.json"
    if official.exists():
        auth = json.loads(official.read_text("utf-8")).get("authorization")
        if auth:
            return auth
    zcode = Path.home() / ".zcode" / "cli" / "config.json"
    if zcode.exists():
        for server in json.loads(zcode.read_text("utf-8")).get("mcp", {}).get("servers", {}).values():
            auth = (server.get("headers") or {}).get("Authorization")
            if auth and "pkulaw" in (server.get("url") or ""):
                return auth
    raise PkulawError("找不到法宝令牌：请设置环境变量 PKULAW_MCP_AUTHORIZATION")


def parse_response(body: bytes, content_type: str) -> dict | None:
    """网关可能回 JSON 或 SSE；SSE 不带 charset，必须显式按 UTF-8 解码（按 latin-1 会把汉字切出假换行）。"""
    text = body.decode("utf-8")
    if "text/event-stream" in content_type:
        messages = []
        for block in text.replace("\r\n", "\n").split("\n\n"):
            data = "".join(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
            if data:
                messages.append(json.loads(data))
        return messages[-1] if messages else None
    return json.loads(text) if text.strip() else None


def urllib_transport(url: str, headers: dict, body: bytes, timeout: float = 90) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def cache_key(path: str, tool: str, arguments: dict) -> str:
    canonical = json.dumps({"path": path, "tool": tool, "arguments": arguments},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


class Session:
    """一个服务端点上的 MCP 会话。"""

    def __init__(self, url: str, authorization: str, transport: Transport):
        self.url = url
        self.authorization = authorization
        self.transport = transport
        self.session_id: str | None = None
        self.next_id = 0
        self.ready = False

    def rpc(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self.next_id += 1
            message["id"] = self.next_id
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "Authorization": self.authorization}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        status, resp_headers, body = self.transport(self.url, headers, json.dumps(message).encode("utf-8"))
        lowered = {k.lower(): v for k, v in resp_headers.items()}
        self.session_id = lowered.get("mcp-session-id") or self.session_id
        if status >= 400:
            raise PkulawError(f"{self.url} HTTP {status}：{body.decode('utf-8', 'replace')[:300]}")
        return parse_response(body, lowered.get("content-type", "")) if body else None

    def ensure_ready(self) -> None:
        if not self.ready:
            self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "justilaw-pkulaw-mcp", "version": "0.2"}})
            self.rpc("notifications/initialized", notify=True)
            self.ready = True


@dataclass
class Gateway:
    """所有服务共用的入口：令牌、预算、缓存、台账。

    budget：本次运行最多花多少积分（None = 不设上限，不建议）。
    offline：只读缓存，未命中就报错；用于复现与测试。
    """
    budget: int | None = None
    workstream: str = "engine"
    data_dir: Path = DATA_DIR
    transport: Transport = urllib_transport
    authorization: str | None = None
    offline: bool = False
    gateway: str = GATEWAY
    spent: int = 0
    sessions: dict[str, Session] = field(default_factory=dict)

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "ledger.csv"

    def session(self, path: str) -> Session:
        if path not in self.sessions:
            auth = self.authorization or find_authorization()
            self.sessions[path] = Session(self.gateway + path, auth, self.transport)
        return self.sessions[path]

    def list_tools(self, path: str) -> list[dict]:
        """tools/list 不扣积分。"""
        s = self.session(path)
        s.ensure_ready()
        result = (s.rpc("tools/list", {}) or {}).get("result") or {}
        return result.get("tools") or []

    def call(self, path: str, tool: str, arguments: dict, *, points: int, refresh: bool = False) -> dict:
        """返回 {"structured": ..., "text": ..., "cached": bool}。"""
        arguments = {k: v for k, v in arguments.items() if v is not None}
        key = cache_key(path, tool, arguments)
        cache_file = self.cache_dir / path.strip("/").replace("/", "_") / f"{key}.json"
        if cache_file.exists() and not refresh:
            cached = json.loads(cache_file.read_text("utf-8"))
            self._ledger(path, tool, arguments, 0, True, True, "缓存")
            return {"structured": cached.get("structured"), "text": cached.get("text"), "cached": True}
        if self.offline:
            raise PkulawError(f"离线模式下缓存未命中：{path} {tool} {arguments}")
        if self.budget is not None and self.spent + points > self.budget:
            raise BudgetExceeded(f"本次预算 {self.budget} 分，已花 {self.spent} 分，再调用 {tool}（{points} 分）将超出")
        s = self.session(path)
        s.ensure_ready()
        response = s.rpc("tools/call", {"name": tool, "arguments": arguments}) or {}
        if "error" in response:
            self._ledger(path, tool, arguments, 0, False, False, str(response["error"])[:200])
            raise PkulawError(f"{tool} 调用失败：{response['error']}")
        result = response.get("result") or {}
        text = "\n".join(c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text")
        if result.get("isError"):
            # 网关对参数错误也可能扣分；保守按单价记账
            self.spent += points
            self._ledger(path, tool, arguments, points, False, False, text[:200])
            raise PkulawError(f"{tool} 返回错误：{text[:300]}")
        structured = result.get("structuredContent")
        self.spent += points
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"path": path, "tool": tool, "arguments": arguments,
                                          "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                          "structured": structured, "text": text},
                                         ensure_ascii=False, indent=1), "utf-8")
        note = f"total={structured.get('total')}" if isinstance(structured, dict) and "total" in structured else ""
        self._ledger(path, tool, arguments, points, False, True, note)
        return {"structured": structured, "text": text, "cached": False}

    def seed(self, path: str, tool: str, arguments: dict, response: dict) -> Path:
        """把此前已付费拿到的原始 JSON-RPC 响应写进缓存，避免重复付费。"""
        result = response.get("result") or {}
        text = "\n".join(c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text")
        key = cache_key(path, tool, {k: v for k, v in arguments.items() if v is not None})
        cache_file = self.cache_dir / path.strip("/").replace("/", "_") / f"{key}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"path": path, "tool": tool, "arguments": arguments,
                                          "fetched_at": "seeded", "structured": result.get("structuredContent"),
                                          "text": text}, ensure_ascii=False, indent=1), "utf-8")
        return cache_file

    def _ledger(self, path, tool, arguments, points, cache_hit, ok, note) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        new = not self.ledger_path.exists()
        with self.ledger_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
            if new:
                w.writeheader()
            w.writerow({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "workstream": self.workstream,
                        "service": path, "tool": tool, "arguments": json.dumps(arguments, ensure_ascii=False),
                        "points": points, "cache_hit": int(cache_hit), "ok": int(ok), "note": note})

"""北大法宝 MCP 最小客户端（Streamable HTTP），用于探查与小批量调用。

用法：
  python mcp_probe.py list <path>                  # initialize + tools/list，不扣积分
  python mcp_probe.py call <path> <tool> '<json>'  # tools/call，按服务扣积分（先用 account 服务查单价）
  例：python mcp_probe.py call /pkulaw-account/mcp list_entitlements '{}'
Git Bash 下要加 MSYS_NO_PATHCONV=1，否则以 / 开头的路径会被改写成 Windows 路径。

令牌查找顺序：环境变量 PKULAW_MCP_AUTHORIZATION → ~/.pkulaw/mcp/config.json（官方 CLI）→ ~/.zcode/cli/config.json（数据链路的 ZCode 配置）。
令牌不打印、不写盘；响应写到 $JUSTILAW_DATA_DIR/engine/pkulaw_mcp/（含个人姓名，不进仓库）。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
GATEWAY = "https://apim-gateway.pkulaw.com"
DATA = Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research"))
OUT = DATA / "engine" / "pkulaw_mcp"


def authorization() -> str:
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
        for s in json.loads(zcode.read_text("utf-8")).get("mcp", {}).get("servers", {}).values():
            auth = (s.get("headers") or {}).get("Authorization")
            if auth and "pkulaw" in (s.get("url") or ""):
                return auth
    raise SystemExit("找不到法宝令牌：请设置 PKULAW_MCP_AUTHORIZATION")


def parse(body: bytes, ctype: str):
    text = body.decode("utf-8")  # 网关的 SSE 响应不带 charset，必须显式按 UTF-8 解码
    if "text/event-stream" in ctype:
        msgs = []
        for block in text.split("\n\n"):
            data = "".join(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
            if data:
                msgs.append(json.loads(data))
        return msgs[-1] if msgs else None
    return json.loads(text) if text.strip() else None


class Client:
    def __init__(self, path: str):
        self.url = GATEWAY + path
        self.auth = authorization()
        self.session = None
        self.n = 0

    def rpc(self, method: str, params=None, notify: bool = False):
        self.n += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            msg["id"] = self.n
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "Authorization": self.auth}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                self.session = r.headers.get("Mcp-Session-Id") or self.session
                return parse(r.read(), r.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as e:
            return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:500]}

    def initialize(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "justilaw-probe", "version": "0.1"}})
        self.rpc("notifications/initialized", notify=True)
        return r


def main():
    mode, path = sys.argv[1], sys.argv[2]
    OUT.mkdir(parents=True, exist_ok=True)
    client = Client(path)
    init = client.initialize()
    tag = path.strip("/").replace("/", "_")
    if mode == "list":
        r = client.rpc("tools/list", {})
        (OUT / f"{tag}.tools.json").write_text(json.dumps({"init": init, "tools": r}, ensure_ascii=False, indent=1), "utf-8")
        tools = ((r or {}).get("result") or {}).get("tools") or []
        print(f"{path}: {((init or {}).get('result') or {}).get('serverInfo')}，工具 {len(tools)} 个", "" if tools else r)
        for t in tools:
            schema = t.get("inputSchema") or {}
            required = schema.get("required") or []
            print(f"  - {t['name']}: {(t.get('description') or '').strip()[:160]}")
            for k, v in (schema.get("properties") or {}).items():
                enum = f" enum={v['enum']}" if v.get("enum") else ""
                print(f"      {'*' if k in required else ' '} {k} ({v.get('type')}){enum}: {(v.get('description') or '').replace(chr(10), ' ')[:120]}")
    else:
        tool, args = sys.argv[3], json.loads(sys.argv[4])
        t0 = time.time()
        r = client.rpc("tools/call", {"name": tool, "arguments": args})
        path_out = OUT / f"{tag}.{tool}.{time.strftime('%Y%m%d-%H%M%S')}.json"
        path_out.write_text(json.dumps({"arguments": args, "response": r}, ensure_ascii=False, indent=1), "utf-8")
        res = (r or {}).get("result") or {}
        sc = res.get("structuredContent")
        print(f"耗时 {time.time() - t0:.1f}s，isError={res.get('isError')}，已存 {path_out}")
        print(json.dumps(sc if sc is not None else (res.get("content") or r), ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()

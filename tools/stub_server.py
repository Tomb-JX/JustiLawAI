"""本地打桩服务：一个最小的 OpenAI 兼容接口，用来验证客户端整条链路。

它不是模型，也不会做任何法律判断。它只做两件事：
  1. GET  /v1/models            —— 让「测试连接」能亮绿灯
  2. POST /v1/chat/completions  —— 按 SSE 一段一段吐固定文本（顺带回显收到的输入）

用途只有一个：在没有接真模型的时候，确认「打开文件 -> 发请求 -> 流式显示 -> 另存为」是通的。

    python tools/stub_server.py

然后把客户端设置里的接口地址填成 http://127.0.0.1:8000/v1
"""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {"object": "list", "data": [{"id": "justilaw-stub", "object": "model"}]}

TAIL = [
    "\n\n【打桩服务固定回复】\n",
    "一、案件事实摘要\n",
    "（打桩服务不读材料，这里只证明客户端把材料发出来了。）\n\n",
    "二、可认定的事实要素\n",
    "赌资数额：材料未载明\n",
    "参赌人数：材料未载明\n",
    "抽头渔利：材料未载明\n",
    "是否提供赌博条件：材料未载明\n",
    "组织形式：材料未载明\n",
    "前科劣迹：材料未载明\n",
    "从轻或者减轻情节：材料未载明\n\n",
    "三、拟适用的法律条文\n",
    "《中华人民共和国治安管理处罚法》第八十二条（2026-01-01 施行）\n\n",
    "四、裁量考虑要点\n",
    "上述数字全部需要办案人员从材料中确认，打桩服务不产生任何数值。\n",
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音，免得刷屏
        pass

    def _send(self, code, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, json.dumps(MODELS).encode("utf-8"), "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, b'{"error":"not found"}', "application/json")
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        user_text = ""
        for message in payload.get("messages", []):
            if message.get("role") == "user":
                user_text = message.get("content") or ""

        head = [
            f"【打桩服务】收到 {len(user_text)} 字的输入。\n",
            f"模型名写的是 {payload.get('model')!r}，temperature={payload.get('temperature')}，stream={payload.get('stream')}。\n",
            "输入的开头是：" + user_text[:40].replace("\n", " ") + "\n",
        ]

        # 不用 Content-Length，改发 Connection: close：客户端一直读到流结束就行。
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        for piece in head + TAIL:
            chunk = {"choices": [{"index": 0, "delta": {"content": piece}}]}
            self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.02)  # 慢一点，肉眼能看出是流式的

        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("stub listening on http://127.0.0.1:8000/v1", flush=True)
    server.serve_forever()

"""法宝 MCP 调用层：解析、缓存、预算、台账（全部用假传输，不连网、不花积分）。

运行：research/.venv/Scripts/python -m pytest research/eval/tests -q
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pkulaw_mcp import BudgetExceeded, Gateway, Pkulaw, PkulawError  # noqa: E402
from pkulaw_mcp.client import cache_key, parse_response  # noqa: E402

TOKEN = "Bearer secret-token-should-never-leak"


class FakeTransport:
    """记录请求；initialize 回 JSON，tools/call 回 SSE（模拟网关不带 charset 的情况）。"""

    def __init__(self, structured=None, is_error=False):
        self.calls = []
        self.structured = structured if structured is not None else {"total": 3, "data": []}
        self.is_error = is_error

    def __call__(self, url, headers, body):
        msg = json.loads(body)
        self.calls.append((url, msg.get("method"), headers))
        if msg["method"] == "initialize":
            return 200, {"Content-Type": "application/json", "Mcp-Session-Id": "s1"}, json.dumps(
                {"jsonrpc": "2.0", "id": msg["id"], "result": {"serverInfo": {"name": "fake"}}}).encode()
        if msg["method"] == "notifications/initialized":
            return 202, {}, b""
        result = {"content": [{"type": "text", "text": "检索到 3 条"}], "isError": self.is_error,
                  "structuredContent": self.structured}
        payload = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}, ensure_ascii=False)
        return 200, {"Content-Type": "text/event-stream"}, f"event: message\ndata: {payload}\n\n".encode("utf-8")

    @property
    def tool_calls(self):
        return [c for c in self.calls if c[1] == "tools/call"]


@pytest.fixture
def gw(tmp_path):
    return Gateway(budget=200, data_dir=tmp_path, transport=FakeTransport(), authorization=TOKEN)


def test_parse_sse_utf8_without_charset():
    body = 'data: {"result": {"text": "赌博案"}}\n\n'.encode("utf-8")
    assert parse_response(body, "text/event-stream")["result"]["text"] == "赌博案"


def test_cache_key_ignores_argument_order():
    assert cache_key("/p", "t", {"a": 1, "b": [1, 2]}) == cache_key("/p", "t", {"b": [1, 2], "a": 1})


def test_session_header_reused(gw):
    Pkulaw(gw).search_enforcement("赌博")
    call = gw.transport.tool_calls[0]
    assert call[2]["Mcp-Session-Id"] == "s1"


def test_second_identical_call_is_free(gw):
    pk = Pkulaw(gw)
    first = pk.search_enforcement("赌博", target=["个人"])
    second = pk.search_enforcement("赌博", target=["个人"])
    assert not first["cached"] and second["cached"]
    assert len(gw.transport.tool_calls) == 1
    assert gw.spent == 75


def test_budget_blocks_before_request(gw):
    pk = Pkulaw(gw)
    pk.search_enforcement("赌博")
    pk.search_enforcement("开设赌场")
    with pytest.raises(BudgetExceeded):
        pk.search_enforcement("聚众赌博")
    assert len(gw.transport.tool_calls) == 2 and gw.spent == 150


def test_none_arguments_dropped(gw):
    Pkulaw(gw).search_enforcement("赌博", regions=None, start=None)
    files = list((gw.cache_dir).rglob("*.json"))
    args = json.loads(files[0].read_text("utf-8"))["arguments"]
    assert args == {"queryText": "赌博", "searchType": "keyword"}


def test_tool_error_raises_and_is_not_cached(tmp_path):
    gw = Gateway(budget=200, data_dir=tmp_path, transport=FakeTransport(is_error=True), authorization=TOKEN)
    with pytest.raises(PkulawError):
        Pkulaw(gw).law_item("刑法", 2)
    assert not list(gw.cache_dir.rglob("*.json"))


def test_offline_mode_never_sends(tmp_path):
    gw = Gateway(budget=200, data_dir=tmp_path, transport=FakeTransport(), authorization=TOKEN, offline=True)
    with pytest.raises(PkulawError):
        Pkulaw(gw).article_history("治安管理处罚法", "82")
    assert gw.transport.calls == []


def test_seeded_response_is_served_from_cache(gw):
    raw = {"result": {"content": [{"type": "text", "text": "x"}], "structuredContent": {"articleLabel": "第八十二条"}}}
    gw.seed("/pkulaw-statute-history/mcp", "get_article_history", {"lawTitle": "治安管理处罚法", "articleNumber": "82"}, raw)
    r = Pkulaw(gw).article_history("治安管理处罚法", "82")
    assert r["cached"] and r["structured"]["articleLabel"] == "第八十二条"
    assert gw.transport.calls == []


def test_ledger_records_points_and_never_the_token(gw):
    pk = Pkulaw(gw)
    pk.search_enforcement("赌博")
    pk.search_enforcement("赌博")
    rows = list(csv.DictReader(gw.ledger_path.open(encoding="utf-8")))
    assert [int(r["points"]) for r in rows] == [75, 0]
    assert rows[0]["note"] == "total=3"
    stored = gw.ledger_path.read_text("utf-8") + "".join(p.read_text("utf-8") for p in gw.cache_dir.rglob("*.json"))
    assert "secret-token" not in stored


def test_list_requires_some_keyword(gw):
    with pytest.raises(PkulawError):
        Pkulaw(gw).law_list()

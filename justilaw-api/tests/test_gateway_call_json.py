"""网关 call_json：结构化输出、seed 透传、json_schema 不支持时退回、回执字段；不发真实请求。"""
import asyncio
import json

import httpx
import pytest

from app.model_gateway import gateway
from app.model_gateway.gateway import Provider


def run(provider, handler, params, monkeypatch):
    monkeypatch.setattr(gateway, "_resolve_or_raise", lambda mid: _async((provider, "m1")))
    monkeypatch.setattr(gateway.provider_store, "model_info", lambda mid: {"capabilities": ["completion"]})
    monkeypatch.setattr(Provider, "client", lambda self, timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return asyncio.run(gateway.call_json("p/m1", [{"role": "user", "content": "hi"}], params))


async def _async(v):
    return v


def test_openai_compat_schema_fallback_seed_and_receipt(monkeypatch):
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, text="unsupported response_format")
        return httpx.Response(200, json={"id": "c1", "model": "m1-0501", "choices": [
            {"message": {"content": "{\"a\":1}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    p = Provider(id="p", name="P", type="openai_compat", base_url="http://x/v1", api_key="sk-secret")
    text, rc = run(p, handler, {"response_schema": {"type": "object"}, "seed": 7, "temperature": 0,
                                "extra_body": {"enable_thinking": False, "model": "hijack"}}, monkeypatch)
    assert text == "{\"a\":1}" and seen[0]["seed"] == 7 and seen[0]["model"] == "m1"
    assert seen[0]["enable_thinking"] is False and seen[1]["response_format"] == {"type": "json_object"}
    assert rc["schema_fallback"] and rc["response_model"] == "m1-0501" and rc["response_id"] == "c1"
    assert rc["usage"] == {"prompt_tokens": 3, "completion_tokens": 2} and len(rc["response_sha256"]) == 64
    assert "sk-secret" not in json.dumps(rc)


def test_ollama_format_seed_and_failure_receipt(monkeypatch):
    seen = []

    def ok(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"model": "m1", "message": {"content": "{}"}, "done_reason": "stop",
                                         "prompt_eval_count": 4, "eval_count": 1})

    p = Provider(id="ollama", name="O", type="ollama", base_url="http://127.0.0.1:11434")
    _, rc = run(p, ok, {"json": True, "seed": 1}, monkeypatch)
    assert seen[0]["format"] == "json" and seen[0]["options"]["seed"] == 1 and seen[0]["stream"] is False
    assert rc["status"] == "ok" and rc["usage"]["prompt_tokens"] == 4

    with pytest.raises(RuntimeError) as e:
        run(p, lambda req: httpx.Response(500, text="boom"), {"json": True}, monkeypatch)
    assert e.value.receipt["status"] == "fail" and "latency_ms" in e.value.receipt

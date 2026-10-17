"""Official API adapters for the three approved flagship model families.

No local endpoint, arbitrary base URL, or small model is accepted.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

MODELS = {
    "deepseek": ("deepseek-v4-pro", "DEEPSEEK_API_KEY"),
    "qwen": ("qwen3.8-max", "DASHSCOPE_API_KEY"),
    "kimi": ("kimi-k3", "DASHSCOPE_API_KEY"),
    "openai": ("gpt-6-astra", "OPENAI_API_KEY"),
}
REVIEW_TRIO = ("deepseek", "qwen", "kimi")


def endpoint(provider: str) -> str:
    if provider == "deepseek":
        return "https://api.deepseek.com/chat/completions"
    if provider == "openai":
        return "https://api.openai.com/v1/responses"
    if provider not in ("qwen", "kimi"):
        raise ValueError("Provider is not on the flagship allowlist")
    base = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    parsed = urllib.parse.urlparse(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "dashscope.aliyuncs.com"
                                          or host.endswith(".maas.aliyuncs.com")):
        raise ValueError("QWEN_BASE_URL must be an official Alibaba Cloud HTTPS endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("QWEN_BASE_URL has unsupported URL components")
    return base.rstrip("/") + "/chat/completions"


def configured(provider: str) -> bool:
    if provider not in MODELS:
        raise ValueError("Provider is not on the flagship allowlist")
    endpoint(provider)
    return bool(os.getenv(MODELS[provider][1]))


def call_json(provider: str, system: str, user: str, *, timeout: int = 180) -> dict:
    if provider not in MODELS:
        raise ValueError("Provider is not on the flagship allowlist")
    model, key_name = MODELS[provider]
    key = os.getenv(key_name)
    if not key:
        raise RuntimeError(f"Missing {key_name}; no request was sent")
    url = endpoint(provider)
    if provider == "openai":
        payload = {"model": model, "instructions": system, "input": user,
                   "store": False, "reasoning": {"effort": "high"}}
    else:
        payload = {"model": model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False, "response_format": {"type": "json_object"}}
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as handle:
            response = json.load(handle)
    except urllib.error.HTTPError as exc:
        # Provider error bodies can echo source text; never print or retain them.
        raise RuntimeError(f"Provider HTTP {exc.code}") from None
    if provider == "openai":
        if response.get("status") != "completed":
            raise RuntimeError("OpenAI response not completed")
        parts = [part.get("text", "") for item in response.get("output", [])
                 if item.get("type") == "message"
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        content = "".join(parts)
    else:
        content = response["choices"][0]["message"]["content"]
    answer = json.loads(content)
    if not isinstance(answer, dict):
        raise ValueError("Model output must be a JSON object")
    return {"provider": provider, "requested_model": model,
            "returned_model": response.get("model"), "response_id": response.get("id"),
            "answer": answer}

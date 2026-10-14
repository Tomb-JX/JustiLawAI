"""模型网关：统一抽象 Ollama 与 OpenAI 兼容自定义 API。

设计对齐主流智能体平台（Dify / LobeChat / Open WebUI）的"模型供应商"体系：
- Provider = 一组连接配置（类型 + base_url + api_key）
- 平台模型 ID 形如 "ollama/qwen3.5:9b" 或 "custom-<provider_id>/<model>"
- 网关按前缀路由到对应 Provider，上层路由不感知差异
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from .. import config


# ---------- 供应商数据模型 ----------

@dataclass
class Provider:
    id: str
    name: str
    type: str                     # 'ollama' | 'openai_compat'
    base_url: str
    api_key: str = ""
    enabled: bool = True
    models: list[dict] = field(default_factory=list)   # [{id, name, capabilities, default_params}]

    def public(self) -> dict:
        d = self.__dict__.copy()
        d["api_key"] = ("*" * 8 + self.api_key[-4:]) if self.api_key else ""
        return d


class ProviderStore:
    """Provider 持久化（JSON）。内置 Ollama 供应商不可删除。"""

    def __init__(self):
        self.path = config.DATA_DIR / "providers.json"
        builtin = Provider(
            id="ollama",
            name="Ollama（本地）",
            type="ollama",
            base_url=config.OLLAMA_BASE_URL,
        )
        self._providers: dict[str, Provider] = {"ollama": builtin}
        self._load()
        self._auto_register_ollama_models()

    def _load(self):
        if self.path.exists():
            raw = json.loads(self.path.read_text("utf-8"))
            for p in raw:
                if p["id"] != "ollama":
                    self._providers[p["id"]] = Provider(**p)
                else:  # 保留内置，但允许改名/启停
                    self._providers["ollama"].name = p.get("name", self._providers["ollama"].name)
                    self._providers["ollama"].enabled = p.get("enabled", True)

    def _save(self):
        self.path.write_text(
            json.dumps([p.__dict__ for p in self._providers.values()], ensure_ascii=False, indent=2),
            "utf-8",
        )

    def _auto_register_ollama_models(self):
        """启动时从 /api/tags 自动发现 Ollama 模型（幂等）。"""
        try:
            r = httpx.get(f"{self._providers['ollama'].base_url}/api/tags", timeout=5)
            tags = r.json().get("models", [])
        except Exception:
            tags = []
        existing = {m["id"] for m in self._providers["ollama"].models}
        for t in tags:
            mid = f"ollama/{t['name']}"
            if mid in existing:
                continue
            caps = t.get("capabilities", [])
            self._providers["ollama"].models.append({
                "id": mid,
                "name": t["name"],
                "capabilities": caps or ["completion"],
                "default_params": {"temperature": 0.7, "top_p": 0.9, "max_tokens": 2048},
            })
        # 嵌入模型（bge-m3 等 embedding family）
        self._providers["ollama"].models.append({
            "id": f"ollama/{config.DEFAULT_EMBED_MODEL}",
            "name": f"{config.DEFAULT_EMBED_MODEL}（嵌入）",
            "capabilities": ["embedding"],
            "default_params": {"temperature": 0, "top_p": 1, "max_tokens": 0},
        })
        self._save()

    # ---- CRUD ----
    def list(self) -> list[Provider]:
        return list(self._providers.values())

    def get(self, pid: str) -> Provider | None:
        return self._providers.get(pid)

    def add(self, **kw) -> Provider:
        pid = kw.get("id") or f"custom-{len(self._providers):03d}"
        while pid in self._providers:
            pid += "-x"
        kw["id"] = pid
        kw.setdefault("type", "openai_compat")
        kw.setdefault("models", [])
        p = Provider(**kw)
        self._providers[pid] = p
        self._save()
        return p

    def update(self, pid: str, patch: dict) -> Provider | None:
        p = self._providers.get(pid)
        if not p:
            return None
        for k, v in patch.items():
            if k not in ("id", "type") and v is not None:
                setattr(p, k, v)
        self._save()
        return p

    def delete(self, pid: str) -> bool:
        if pid == "ollama":
            return False
        if pid not in self._providers:
            return False
        del self._providers[pid]
        self._save()
        return True

    def add_model(self, pid: str, model: dict) -> dict | None:
        p = self._providers.get(pid)
        if not p:
            return None
        mid = model["id"] if "/" in model["id"] else f"{pid}/{model['id']}"
        model["id"] = mid
        model.setdefault("capabilities", ["completion"])
        model.setdefault("default_params", {"temperature": 0.7, "top_p": 0.9, "max_tokens": 2048})
        p.models = [m for m in p.models if m["id"] != mid] + [model]
        self._save()
        return model

    def remove_model(self, pid: str, mid: str) -> bool:
        p = self._providers.get(pid)
        if not p:
            return False
        before = len(p.models)
        p.models = [m for m in p.models if m["id"] != mid]
        self._save()
        return len(p.models) < before

    # ---- 查询 ----
    def all_models(self) -> list[dict]:
        out = []
        for p in self._providers.values():
            if not p.enabled:
                continue
            for m in p.models:
                out.append({**m, "provider": p.id, "provider_name": p.name, "provider_type": p.type})
        return out

    def resolve(self, platform_model_id: str) -> tuple[Provider, str] | None:
        """平台模型 ID → (Provider, 真实模型名)。"""
        for p in self._providers.values():
            if p.enabled and platform_model_id.startswith(p.id + "/"):
                return p, platform_model_id[len(p.id) + 1:]
        # 容错：裸模型名默认走 Ollama
        if any(m["id"] == platform_model_id for m in self._providers["ollama"].models):
            return self._providers["ollama"], platform_model_id.split("/", 1)[-1]
        return None


provider_store = ProviderStore()


# ---------- 聊天流（统一增量结构） ----------

@dataclass
class ChatDelta:
    text: str = ""
    thinking: str = ""


async def stream_chat(
    model_id: str,
    messages: list[dict],
    params: dict,
    thinking: bool = False,
) -> AsyncIterator[ChatDelta]:
    """统一对话流：yield ChatDelta(text=..., thinking=...)"""
    resolved = provider_store.resolve(model_id)
    if not resolved:
        raise RuntimeError(f"未注册的模型：{model_id}")
    provider, real_model = resolved

    if provider.type == "ollama":
        payload = {
            "model": real_model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": params.get("temperature", 0.7),
                "top_p": params.get("top_p", 0.9),
                "num_predict": params.get("max_tokens", 2048),
            },
        }
        if thinking:
            payload["think"] = True
        else:
            payload["think"] = False   # qwen3.5 等模型默认开启思维链，显式关闭提速
        url = f"{provider.base_url}/api/chat"
        headers = {}
    else:  # openai_compat
        payload = {
            "model": real_model,
            "messages": messages,
            "stream": True,
            "temperature": params.get("temperature", 0.7),
            "top_p": params.get("top_p", 0.9),
            "max_tokens": params.get("max_tokens", 2048),
        }
        url = provider.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}

    async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT_S) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                raise RuntimeError(f"上游 {resp.status_code}：{body}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                if provider.type == "ollama":
                    # Ollama 原生流：每行一个裸 JSON 对象（非 SSE）
                    try:
                        j = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = j.get("message", {})
                    t = msg.get("content") or ""
                    th = msg.get("thinking") or ""
                    if t or th:
                        yield ChatDelta(text=t, thinking=th)
                else:
                    # OpenAI 兼容流：SSE data: 前缀
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        j = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = j.get("choices") or []
                    if not choices:
                        continue
                    d = choices[0].get("delta", {})
                    rc = d.get("reasoning_content") or ""   # DeepSeek 等兼容思维链
                    t = d.get("content") or ""
                    if t or rc:
                        yield ChatDelta(text=t, thinking=rc)


async def embed_texts(model_id: str, texts: list[str]) -> list[list[float]]:
    """批量文本嵌入。Ollama 用 /api/embed；自定义 API 走 OpenAI 兼容 /embeddings。"""
    resolved = provider_store.resolve(model_id)
    if not resolved:
        raise RuntimeError(f"未注册的嵌入模型：{model_id}")
    provider, real_model = resolved
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=120) as client:
        for i in range(0, len(texts), config.EMBED_BATCH_SIZE):
            batch = texts[i : i + config.EMBED_BATCH_SIZE]
            if provider.type == "ollama":
                r = await client.post(
                    f"{provider.base_url}/api/embed", json={"model": real_model, "input": batch}
                )
                r.raise_for_status()
                out.extend(r.json()["embeddings"])
            else:
                headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
                r = await client.post(
                    provider.base_url.rstrip("/") + "/embeddings",
                    json={"model": real_model, "input": batch},
                    headers=headers,
                )
                r.raise_for_status()
                out.extend(item["embedding"] for item in r.json()["data"])
    return out


async def ping_provider(provider: Provider) -> int:
    """连通性测试，返回延迟 ms；失败抛异常。"""
    import time

    t0 = time.time()
    if provider.type == "ollama":
        r = await httpx.AsyncClient(timeout=8).get(f"{provider.base_url}/api/tags")
        r.raise_for_status()
    else:
        headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
        r = await httpx.AsyncClient(timeout=8).get(
            provider.base_url.rstrip("/") + "/models", headers=headers
        )
        r.raise_for_status()
    return int((time.time() - t0) * 1000)

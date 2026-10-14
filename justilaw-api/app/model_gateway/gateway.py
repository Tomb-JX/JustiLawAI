"""模型网关：统一抽象 Ollama 与 OpenAI 兼容自定义 API。

设计对齐主流智能体平台（Dify / LobeChat / Open WebUI）的"模型供应商"体系：
- Provider = 一组连接配置（类型 + base_url + api_key）
- 平台模型 ID 形如 "ollama/qwen3.5:9b" 或 "<provider_id>/<model>"
- 模型按能力标签路由：completion（对话）/ embedding（嵌入）/ vision / tools / thinking
- 默认对话模型、默认嵌入模型可在运行时配置（settings_db），上层路由不感知供应商差异
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

from .. import config
from ..store import settings_db

DEFAULT_PARAMS = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 2048}
EMBED_PARAMS = {"temperature": 0, "top_p": 1, "max_tokens": 0}
OLLAMA_REFRESH_INTERVAL_S = 30


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

    @property
    def auto_discover(self) -> bool:
        return self.type == "ollama"

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, trust_env=not _is_loopback(self.base_url))


def _is_loopback(url: str) -> bool:
    """本机服务不走系统代理：开着 HTTP(S)_PROXY 时请求 127.0.0.1 会被代理转发而失败。"""
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


class ProviderStore:
    """Provider 持久化（JSON）。内置 Ollama 供应商不可删除；Ollama 类供应商的模型自动发现。"""

    def __init__(self):
        self.path = config.DATA_DIR / "providers.json"
        self._providers: dict[str, Provider] = {
            "ollama": Provider(id="ollama", name="Ollama（本地）", type="ollama",
                               base_url=config.OLLAMA_BASE_URL),
        }
        self._last_refresh: dict[str, float] = {}
        self._load()
        for p in self._providers.values():
            if p.auto_discover:
                self.refresh(p.id)

    def _load(self):
        if not self.path.exists():
            return
        for raw in json.loads(self.path.read_text("utf-8")):
            if raw["id"] == "ollama":  # 内置供应商只保留可改的展示项与地址
                builtin = self._providers["ollama"]
                builtin.name = raw.get("name", builtin.name)
                builtin.enabled = raw.get("enabled", True)
                continue
            self._providers[raw["id"]] = Provider(**raw)

    def _save(self):
        self.path.write_text(
            json.dumps([p.__dict__ for p in self._providers.values()], ensure_ascii=False, indent=2),
            "utf-8",
        )

    def refresh(self, pid: str) -> bool:
        """从 Ollama /api/tags 同步模型清单（含能力标签）。失败时保留旧清单，返回是否成功。"""
        p = self._providers.get(pid)
        if not p or not p.auto_discover:
            return False
        self._last_refresh[pid] = time.time()
        try:
            r = httpx.get(f"{p.base_url}/api/tags", timeout=5, trust_env=not _is_loopback(p.base_url))
            r.raise_for_status()
            tags = r.json().get("models", [])
        except Exception:
            return False
        old = {m["id"]: m for m in p.models}
        models = []
        for t in tags:
            mid = f"{pid}/{t['name']}"
            caps = t.get("capabilities") or _guess_caps(t)
            prev = old.get(mid, {})
            models.append({
                "id": mid,
                "name": t["name"],
                "capabilities": caps,
                # 保留用户调过的默认参数
                "default_params": prev.get("default_params")
                or (EMBED_PARAMS if caps == ["embedding"] else DEFAULT_PARAMS),
            })
        p.models = models
        self._save()
        return True

    def _maybe_refresh(self):
        for p in self._providers.values():
            if p.auto_discover and p.enabled and \
                    time.time() - self._last_refresh.get(p.id, 0) > OLLAMA_REFRESH_INTERVAL_S:
                self.refresh(p.id)

    # ---- CRUD ----
    def list(self) -> list[Provider]:
        self._maybe_refresh()
        return list(self._providers.values())

    def get(self, pid: str) -> Provider | None:
        return self._providers.get(pid)

    def add(self, **kw) -> Provider:
        base = kw.get("id") or "custom"
        pid, n = base, 1
        while pid in self._providers:
            n += 1
            pid = f"{base}-{n}"
        kw["id"] = pid
        kw.setdefault("type", "openai_compat")
        kw.setdefault("models", [])
        p = Provider(**kw)
        self._providers[pid] = p
        if p.auto_discover:
            self.refresh(pid)
        self._save()
        return p

    def update(self, pid: str, patch: dict) -> Provider | None:
        p = self._providers.get(pid)
        if not p:
            return None
        for k, v in patch.items():
            if k in ("name", "base_url", "api_key", "enabled") and v is not None:
                if pid == "ollama" and k == "base_url":
                    continue
                setattr(p, k, v.rstrip("/") if k == "base_url" else v)
        self._save()
        return p

    def delete(self, pid: str) -> bool:
        if pid == "ollama" or pid not in self._providers:
            return False
        del self._providers[pid]
        self._save()
        return True

    def add_model(self, pid: str, model: dict) -> dict | None:
        p = self._providers.get(pid)
        if not p:
            return None
        real = model["id"].split("/", 1)[1] if model["id"].startswith(pid + "/") else model["id"]
        caps = model.get("capabilities") or ["completion"]
        entry = {
            "id": f"{pid}/{real}",
            "name": model.get("name") or real,
            "capabilities": caps,
            "default_params": model.get("default_params")
            or (EMBED_PARAMS if "embedding" in caps and "completion" not in caps else DEFAULT_PARAMS),
        }
        p.models = [m for m in p.models if m["id"] != entry["id"]] + [entry]
        self._save()
        return entry

    def update_model(self, pid: str, mid: str, patch: dict) -> dict | None:
        p = self._providers.get(pid)
        m = next((m for m in p.models if m["id"] == mid), None) if p else None
        if not m:
            return None
        for k in ("name", "capabilities", "default_params"):
            if k in patch and patch[k] is not None:
                m[k] = patch[k]
        self._save()
        return m

    def remove_model(self, pid: str, mid: str) -> bool:
        p = self._providers.get(pid)
        if not p:
            return False
        before = len(p.models)
        p.models = [m for m in p.models if m["id"] != mid]
        self._save()
        return len(p.models) < before

    # ---- 查询 ----
    def all_models(self, capability: str | None = None) -> list[dict]:
        self._maybe_refresh()
        out = []
        for p in self._providers.values():
            if not p.enabled:
                continue
            for m in p.models:
                if capability and capability not in m.get("capabilities", []):
                    continue
                out.append({**m, "provider": p.id, "provider_name": p.name, "provider_type": p.type})
        return out

    def model_info(self, platform_model_id: str) -> dict | None:
        return next((m for m in self.all_models() if _same_model(m["id"], platform_model_id)), None)

    def resolve(self, platform_model_id: str) -> tuple[Provider, str] | None:
        """平台模型 ID → (Provider, 真实模型名)。裸模型名按 Ollama 处理。"""
        if "/" not in platform_model_id:
            platform_model_id = f"ollama/{platform_model_id}"
        for p in self._providers.values():
            if p.enabled and platform_model_id.startswith(p.id + "/"):
                real = platform_model_id[len(p.id) + 1:]
                # 自动发现的供应商：刚 pull 的模型可能还不在缓存里，补刷一次
                if p.auto_discover and not any(_same_model(m["id"], platform_model_id) for m in p.models):
                    self.refresh(p.id)
                return p, real
        return None

    # ---- 默认模型 ----
    def default_model(self, kind: str) -> str | None:
        """kind: 'chat' | 'embedding'。优先已配置值，失效时回退到首个具备该能力的模型。"""
        capability = "completion" if kind == "chat" else "embedding"
        configured = settings_db.data.get(f"default_{kind}_model") or (
            config.DEFAULT_CHAT_MODEL if kind == "chat" else config.DEFAULT_EMBED_MODEL)
        candidates = self.all_models(capability)
        for m in candidates:
            if _same_model(m["id"], configured):
                return m["id"]
        return candidates[0]["id"] if candidates else None

    def set_default_model(self, kind: str, model_id: str) -> bool:
        capability = "completion" if kind == "chat" else "embedding"
        if not any(m["id"] == model_id for m in self.all_models(capability)):
            return False
        settings_db.data[f"default_{kind}_model"] = model_id
        settings_db.save()
        return True


def _same_model(a: str, b: str) -> bool:
    """Ollama 中 "bge-m3" 与 "bge-m3:latest" 是同一个模型。"""
    strip = lambda s: s.removesuffix(":latest")  # noqa: E731
    return strip(a) == strip(b)


def _guess_caps(tag: dict) -> list[str]:
    """旧版 Ollama 的 /api/tags 不返回 capabilities 时，按模型族粗略判断。"""
    family = (tag.get("details") or {}).get("family", "").lower()
    name = tag.get("name", "").lower()
    if "bert" in family or "embed" in name or name.startswith(("bge", "m3e", "gte")):
        return ["embedding"]
    return ["completion"]


provider_store = ProviderStore()


# ---------- 聊天流（统一增量结构） ----------

@dataclass
class ChatDelta:
    text: str = ""
    thinking: str = ""
    usage: dict | None = None     # 仅最后一个增量携带：{prompt_tokens, completion_tokens}


def _resolve_or_raise(model_id: str) -> tuple[Provider, str]:
    resolved = provider_store.resolve(model_id)
    if not resolved:
        raise RuntimeError(f"未注册或已停用的模型：{model_id}（请在「模型服务」页检查供应商）")
    return resolved


async def stream_chat(
    model_id: str,
    messages: list[dict],
    params: dict,
    thinking: bool = False,
) -> AsyncIterator[ChatDelta]:
    """统一对话流：yield ChatDelta(text=..., thinking=...)，结束时 yield 一个带 usage 的增量。"""
    provider, real_model = _resolve_or_raise(model_id)
    info = provider_store.model_info(f"{provider.id}/{real_model}") or {}
    supports_thinking = "thinking" in info.get("capabilities", [])

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
        # 只对支持思维链的模型传 think：qwen3.5 等默认开启，显式关闭可提速；不支持的模型传了会报错
        if supports_thinking:
            payload["think"] = bool(thinking)
        url = f"{provider.base_url}/api/chat"
    else:  # openai_compat
        payload = {
            "model": real_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": params.get("temperature", 0.7),
            "top_p": params.get("top_p", 0.9),
            "max_tokens": params.get("max_tokens", 2048),
        }
        url = provider.base_url.rstrip("/") + "/chat/completions"

    async with provider.client(config.LLM_TIMEOUT_S) as client:
        resp = await _open_stream(client, url, payload, provider.headers())
        try:
            usage: dict | None = None
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                if provider.type == "ollama":
                    # Ollama 原生流：每行一个裸 JSON 对象（非 SSE）
                    try:
                        j = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if j.get("error"):
                        raise RuntimeError(j["error"])
                    msg = j.get("message", {})
                    t = msg.get("content") or ""
                    th = msg.get("thinking") or ""
                    if t or th:
                        yield ChatDelta(text=t, thinking=th)
                    if j.get("done"):
                        usage = {"prompt_tokens": j.get("prompt_eval_count", 0),
                                 "completion_tokens": j.get("eval_count", 0)}
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
                    if j.get("usage"):
                        u = j["usage"]
                        usage = {"prompt_tokens": u.get("prompt_tokens", 0),
                                 "completion_tokens": u.get("completion_tokens", 0)}
                    choices = j.get("choices") or []
                    if not choices:
                        continue
                    d = choices[0].get("delta", {})
                    rc = d.get("reasoning_content") or ""   # DeepSeek 等兼容思维链
                    t = d.get("content") or ""
                    if t or rc:
                        yield ChatDelta(text=t, thinking=rc)
            yield ChatDelta(usage=usage)
        finally:
            await resp.aclose()


async def _open_stream(client: httpx.AsyncClient, url: str, payload: dict, headers: dict) -> httpx.Response:
    resp = await client.send(client.build_request("POST", url, json=payload, headers=headers), stream=True)
    if resp.status_code == 200:
        return resp
    body = (await resp.aread()).decode("utf-8", "ignore")[:300]
    await resp.aclose()
    # 少数兼容平台不认识 stream_options，去掉后重试一次
    if resp.status_code in (400, 422) and "stream_options" in payload:
        payload = {k: v for k, v in payload.items() if k != "stream_options"}
        return await _open_stream(client, url, payload, headers)
    raise RuntimeError(f"上游 {resp.status_code}：{body}")


async def complete(model_id: str, messages: list[dict], params: dict) -> tuple[str, dict | None]:
    """非流式补全（工作流节点等内部调用）：返回 (全文, usage)。"""
    parts, usage = [], None
    async for d in stream_chat(model_id, messages, params):
        parts.append(d.text)
        if d.usage:
            usage = d.usage
    return "".join(parts), usage


async def embed_texts(model_id: str | None, texts: list[str]) -> list[list[float]]:
    """批量文本嵌入。Ollama 用 /api/embed；自定义 API 走 OpenAI 兼容 /embeddings。"""
    model_id = model_id or provider_store.default_model("embedding")
    if not model_id:
        raise RuntimeError("没有可用的嵌入模型：请在 Ollama 中拉取（如 ollama pull bge-m3）或在「模型服务」页添加嵌入模型")
    provider, real_model = _resolve_or_raise(model_id)
    out: list[list[float]] = []
    async with provider.client(120) as client:
        for i in range(0, len(texts), config.EMBED_BATCH_SIZE):
            batch = texts[i: i + config.EMBED_BATCH_SIZE]
            if provider.type == "ollama":
                r = await client.post(f"{provider.base_url}/api/embed",
                                      json={"model": real_model, "input": batch})
            else:
                r = await client.post(provider.base_url.rstrip("/") + "/embeddings",
                                      json={"model": real_model, "input": batch},
                                      headers=provider.headers())
            if r.status_code != 200:
                raise RuntimeError(f"嵌入模型 {model_id} 调用失败（{r.status_code}）：{r.text[:200]}")
            j = r.json()
            out.extend(j["embeddings"] if provider.type == "ollama" else [d["embedding"] for d in j["data"]])
    return out


async def ping_provider(provider: Provider) -> int:
    """连通性测试，返回延迟 ms；失败抛异常。"""
    t0 = time.time()
    async with provider.client(8) as client:
        if provider.type == "ollama":
            r = await client.get(f"{provider.base_url}/api/tags")
        else:
            r = await client.get(provider.base_url.rstrip("/") + "/models", headers=provider.headers())
        r.raise_for_status()
    return int((time.time() - t0) * 1000)


async def fetch_remote_models(provider: Provider) -> list[str]:
    """拉取远端供应商的模型名列表（只列不存，供前端「添加模型」时点选）。

    - openai_compat：GET /models 解析 OpenAI 格式 data[*].id
    - ollama：GET /api/tags 取 name（与自动发现同源）
    """
    async with provider.client(15) as client:
        if provider.type == "ollama":
            r = await client.get(f"{provider.base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", []) if m.get("name")]
        r = await client.get(provider.base_url.rstrip("/") + "/models", headers=provider.headers())
        r.raise_for_status()
        data = r.json().get("data", [])
        return [m["id"] for m in data if isinstance(m, dict) and m.get("id")]


async def ping_model(model_id: str) -> int:
    """模型级测试：嵌入模型实际嵌入一次；对话模型测供应商连通（不消耗生成额度）。"""
    info = provider_store.model_info(model_id)
    provider, _ = _resolve_or_raise(model_id)
    t0 = time.time()
    if info and info.get("capabilities") == ["embedding"]:
        await embed_texts(model_id, ["ping"])
        return int((time.time() - t0) * 1000)
    return await ping_provider(provider)

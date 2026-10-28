"""模型网关：统一抽象 Ollama 与 OpenAI 兼容自定义 API。

设计对齐主流智能体平台（Dify / LobeChat / Open WebUI）的"模型供应商"体系：
- Provider = 一组连接配置（类型 + base_url + api_key）
- 平台模型 ID 形如 "ollama/qwen3.5:9b" 或 "<provider_id>/<model>"
- 模型按能力标签路由：completion（对话）/ embedding（嵌入）/ vision / tools / thinking
- 默认对话模型、默认嵌入模型可在运行时配置（settings_db），上层路由不感知供应商差异
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
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
OLLAMA_PROBE_TIMEOUT_S = 3
# 向导"自动检测"依次尝试的地址：本机 → Docker 容器访问宿主机
OLLAMA_CANDIDATE_URLS = ("http://127.0.0.1:11434", "http://host.docker.internal:11434")
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][\w.\-/]*(:[\w.\-]+)?$")


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
    """Provider 持久化（JSON）。内置 Ollama 供应商不可删除；Ollama 类供应商的模型自动发现。

    自动发现的网络请求都不在事件循环里同步执行：查询接口只读缓存，过期时投递到后台线程刷新，
    Ollama 不可达也不会拖慢其他接口。
    """

    def __init__(self):
        self.path = config.DATA_DIR / "providers.json"
        self._providers: dict[str, Provider] = {
            "ollama": Provider(id="ollama", name="Ollama（本地）", type="ollama",
                               base_url=config.OLLAMA_BASE_URL),
        }
        self._last_refresh: dict[str, float] = {}
        self._refreshing: set[str] = set()
        self._lock = threading.Lock()
        # 自动发现供应商的最近一次连接结果：{reachable, version, error, checked_at}
        self.status: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        for raw in json.loads(self.path.read_text("utf-8")):
            if raw["id"] == "ollama":  # 内置供应商只保留可改的展示项与地址
                builtin = self._providers["ollama"]
                builtin.name = raw.get("name", builtin.name)
                builtin.enabled = raw.get("enabled", True)
                builtin.base_url = raw.get("base_url") or builtin.base_url
                builtin.models = raw.get("models", [])
                continue
            self._providers[raw["id"]] = Provider(**raw)

    def _save(self):
        rows = []
        for p in self._providers.values():
            d = p.__dict__.copy()
            # 内置 Ollama 的地址与环境变量一致时不落盘，之后改 OLLAMA_BASE_URL 仍能生效
            if p.id == "ollama" and p.base_url == config.OLLAMA_BASE_URL:
                d.pop("base_url")
            rows.append(d)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    def refresh(self, pid: str) -> bool:
        """从 Ollama /api/tags 同步模型清单（含能力标签）。失败时保留旧清单，返回是否成功。

        同步阻塞（最长 OLLAMA_PROBE_TIMEOUT_S），异步代码里用 refresh_async 或 asyncio.to_thread 调用。
        """
        p = self._providers.get(pid)
        if not p or not p.auto_discover:
            return False
        self._last_refresh[pid] = time.time()
        try:
            with httpx.Client(timeout=OLLAMA_PROBE_TIMEOUT_S, trust_env=not _is_loopback(p.base_url)) as c:
                r = c.get(f"{p.base_url}/api/tags")
                r.raise_for_status()
                tags = r.json().get("models", [])
                try:
                    version = c.get(f"{p.base_url}/api/version").json().get("version")
                except Exception:
                    version = None
        except Exception as e:
            self.status[pid] = {"reachable": False, "version": None, "error": _short_error(e),
                                "checked_at": time.time()}
            return False
        self.status[pid] = {"reachable": True, "version": version, "error": None, "checked_at": time.time()}
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

    async def refresh_async(self, pid: str) -> bool:
        return await asyncio.to_thread(self.refresh, pid)

    async def refresh_all(self):
        """启动时调用：后台刷新全部自动发现供应商，不阻塞服务启动。"""
        for p in list(self._providers.values()):
            if p.auto_discover and p.enabled:
                await self.refresh_async(p.id)

    def _maybe_refresh(self):
        """缓存过期时投递后台刷新；本次调用直接用旧缓存返回。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        for p in list(self._providers.values()):
            if not (p.auto_discover and p.enabled) or \
                    time.time() - self._last_refresh.get(p.id, 0) <= OLLAMA_REFRESH_INTERVAL_S:
                continue
            if loop is None:  # 非异步上下文（脚本、测试）直接同步刷新
                self.refresh(p.id)
                continue
            with self._lock:
                if p.id in self._refreshing:
                    continue
                self._refreshing.add(p.id)
                self._last_refresh[p.id] = time.time()
            loop.run_in_executor(None, self._refresh_bg, p.id)

    def _refresh_bg(self, pid: str):
        try:
            self.refresh(pid)
        finally:
            with self._lock:
                self._refreshing.discard(pid)

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
        self._save()
        return p

    def update(self, pid: str, patch: dict) -> Provider | None:
        """更新供应商；Ollama 类改了地址会清空模型缓存，调用方随后应刷新。"""
        p = self._providers.get(pid)
        if not p:
            return None
        for k, v in patch.items():
            if k in ("name", "base_url", "api_key", "enabled") and v is not None:
                if k == "base_url":
                    v = v.strip().rstrip("/")
                    if p.auto_discover and v != p.base_url:
                        p.models = []
                        self.status.pop(pid, None)
                        self._last_refresh.pop(pid, None)
                setattr(p, k, v)
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
                return p, platform_model_id[len(p.id) + 1:]
        return None

    async def resolve_async(self, platform_model_id: str) -> tuple[Provider, str] | None:
        """同 resolve；自动发现的供应商里找不到该模型时（刚 pull 的），先在后台线程补刷一次缓存。"""
        resolved = self.resolve(platform_model_id)
        if resolved:
            p, real = resolved
            if p.auto_discover and not any(_same_model(m["name"], real) for m in p.models):
                await self.refresh_async(p.id)
        return resolved

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


def _short_error(e: Exception) -> str:
    if isinstance(e, httpx.ConnectError):
        return "无法连接（Ollama 未启动或地址错误）"
    if isinstance(e, httpx.TimeoutException):
        return "连接超时"
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return str(e)[:200] or e.__class__.__name__


def _guess_caps(tag: dict) -> list[str]:
    """旧版 Ollama 的 /api/tags 不返回 capabilities 时，按模型族粗略判断。"""
    family = (tag.get("details") or {}).get("family", "").lower()
    name = tag.get("name", "").lower()
    if "bert" in family or "embed" in name or name.startswith(("bge", "m3e", "gte")):
        return ["embedding"]
    return ["completion"]


CAP_SET = {"completion", "embedding", "vision", "tools", "thinking"}


def _guess_caps_from_name(name: str) -> list[str]:
    """OpenAI 兼容端点的上游条目没有任何能力字段时的兜底：按模型族名判断。"""
    n = (name or "").lower()
    if any(k in n for k in ("embed", "bge", "m3e", "gte")):
        return ["embedding"]
    return ["completion"]


def _caps_from_remote_entry(entry: dict) -> list[str] | None:
    """从 OpenAI 兼容 GET /models 条目的字段读取能力标签（各家字段名不一，依次尝试）。

    返回 None 表示该条目没有任何能力信息（调用方决定兜底方式）：
    - capabilities / features：部分网关直接返回标签数组或 {标签: 布尔} 字典
    - supported_parameters：OpenRouter 系网关，tools → tools，reasoning/thinking → thinking
    - architecture.input_modalities：含 image/audio/video/file 视为 vision
    嵌入与非嵌入互斥：命中 embedding 就只返回 embedding（嵌入端点不做对话）。
    """
    found: set[str] = set()
    for key in ("capabilities", "features"):
        v = entry.get(key)
        if isinstance(v, list):
            found |= {str(c).lower() for c in v if isinstance(c, str)}
        elif isinstance(v, dict):
            found |= {str(k).lower() for k, on in v.items() if on}
    sp = entry.get("supported_parameters")
    if isinstance(sp, list):
        low = {str(x).lower() for x in sp if isinstance(x, str)}
        if "tools" in low or "tool_choice" in low:
            found.add("tools")
        if "reasoning" in low or "thinking" in low:
            found.add("thinking")
    arch = entry.get("architecture")
    mods = arch.get("input_modalities") if isinstance(arch, dict) else None
    if isinstance(mods, list) and any(str(x).lower() in ("image", "audio", "video", "file") for x in mods):
        found.add("vision")
    found &= CAP_SET
    if not found:
        return None
    if "embedding" in found:
        return ["embedding"]
    return ["completion", *sorted(found - {"completion", "embedding"})]


provider_store = ProviderStore()


# ---------- 聊天流（统一增量结构） ----------

@dataclass
class ChatDelta:
    text: str = ""
    thinking: str = ""
    usage: dict | None = None     # 仅最后一个增量携带：{prompt_tokens, completion_tokens}


async def _resolve_or_raise(model_id: str) -> tuple[Provider, str]:
    resolved = await provider_store.resolve_async(model_id)
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
    provider, real_model = await _resolve_or_raise(model_id)
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


def _digest(obj) -> str:
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def call_json(model_id: str, messages: list[dict], params: dict) -> tuple[str, dict]:
    """非流式结构化调用（裁量能力层的分段 / 抽取用）：返回 (全文, 回执)。

    params 在 temperature / top_p / max_tokens 之外另认：
    - response_schema：JSON Schema → Ollama `format`，OpenAI 兼容 `response_format: json_schema`；
      上游不认 json_schema（400/422）时退回 `json_object` 一次，回执记 schema_fallback
    - json：True 时只要求 JSON 模式（无 schema）
    - seed：透传（Ollama options.seed；OpenAI 兼容 seed）
    - thinking：仅对带 thinking 能力的 Ollama 模型传 think
    - extra_body：只并入 OpenAI 兼容请求体，不覆盖核心键（如 DashScope enable_thinking）
    - timeout_s
    回执含供应商、真实模型名、上游返回的模型名与 ID、usage、耗时、请求与响应摘要（sha256），不含密钥。
    调用失败抛 RuntimeError，异常对象带 receipt 属性（失败也留回执）。
    """
    provider, real_model = await _resolve_or_raise(model_id)
    info = provider_store.model_info(f"{provider.id}/{real_model}") or {}
    schema, seed = params.get("response_schema"), params.get("seed")
    sent = {k: params[k] for k in ("temperature", "top_p", "max_tokens", "seed", "thinking") if k in params}
    receipt = {"platform_model_id": f"{provider.id}/{real_model}", "provider_id": provider.id,
               "provider_type": provider.type, "model": real_model, "params": sent,
               "structured": "json_schema" if schema else ("json" if params.get("json") else "none"),
               "request_sha256": _digest(messages), "started_at": time.time()}
    if provider.type == "ollama":
        options = {"temperature": params.get("temperature", 0), "top_p": params.get("top_p", 1),
                   "num_predict": params.get("max_tokens", 2048)}
        if seed is not None:
            options["seed"] = seed
        payload = {"model": real_model, "messages": messages, "stream": False, "options": options}
        if schema or params.get("json"):
            payload["format"] = schema or "json"
        if "thinking" in info.get("capabilities", []):
            payload["think"] = bool(params.get("thinking", False))
        url = f"{provider.base_url}/api/chat"
    else:
        payload = {"model": real_model, "messages": messages, "stream": False,
                   "temperature": params.get("temperature", 0), "top_p": params.get("top_p", 1),
                   "max_tokens": params.get("max_tokens", 2048)}
        if seed is not None:
            payload["seed"] = seed
        if schema:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "output", "schema": schema}}
        elif params.get("json"):
            payload["response_format"] = {"type": "json_object"}
        payload.update({k: v for k, v in (params.get("extra_body") or {}).items() if k not in payload})
        url = provider.base_url.rstrip("/") + "/chat/completions"
    t0 = time.monotonic()
    try:
        async with provider.client(params.get("timeout_s", config.LLM_TIMEOUT_S)) as client:
            r = await client.post(url, json=payload, headers=provider.headers())
            if (r.status_code in (400, 422) and provider.type != "ollama"
                    and (payload.get("response_format") or {}).get("type") == "json_schema"):
                payload["response_format"] = {"type": "json_object"}
                receipt["schema_fallback"] = f"上游 {r.status_code} 不支持 json_schema，退回 json_object"
                r = await client.post(url, json=payload, headers=provider.headers())
            if r.status_code != 200:
                raise RuntimeError(f"上游 {r.status_code}：{r.text[:300]}")
            j = r.json()
    except Exception as e:  # noqa: BLE001  失败也留回执
        receipt.update(status="fail", error=_short_error(e), latency_ms=round((time.monotonic() - t0) * 1000))
        err = RuntimeError(f"{model_id} 调用失败：{_short_error(e)}")
        err.receipt = receipt
        raise err from None
    if provider.type == "ollama":
        content = (j.get("message") or {}).get("content") or ""
        usage = {"prompt_tokens": j.get("prompt_eval_count", 0), "completion_tokens": j.get("eval_count", 0)}
        receipt.update(response_model=j.get("model"), finish_reason=j.get("done_reason"))
    else:
        choice = (j.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        u = j.get("usage") or {}
        usage = {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0)}
        receipt.update(response_model=j.get("model"), response_id=j.get("id"),
                       finish_reason=choice.get("finish_reason"), system_fingerprint=j.get("system_fingerprint"))
    receipt.update(status="ok", usage=usage, latency_ms=round((time.monotonic() - t0) * 1000),
                   response_sha256=_digest(content))
    return content, receipt


async def embed_texts(model_id: str | None, texts: list[str]) -> list[list[float]]:
    """批量文本嵌入。Ollama 用 /api/embed；自定义 API 走 OpenAI 兼容 /embeddings。"""
    model_id = model_id or provider_store.default_model("embedding")
    if not model_id:
        raise RuntimeError("没有可用的嵌入模型：请在 Ollama 中拉取（如 ollama pull bge-m3）或在「模型服务」页添加嵌入模型")
    provider, real_model = await _resolve_or_raise(model_id)
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


async def fetch_remote_models(provider: Provider) -> list[dict]:
    """拉取远端供应商的模型列表（只列不存），供「添加模型」点选。

    返回 [{id, capabilities}]：能力标签直接读上游返回的字段，不再要求用户手动填写。
    - openai_compat：GET /models → data[*].id + 能力字段（_caps_from_remote_entry），无信息时按族名兜底
    - ollama：GET /api/tags 的 name + capabilities（与自动发现同源）
    """
    async with provider.client(15) as client:
        if provider.type == "ollama":
            r = await client.get(f"{provider.base_url}/api/tags")
            r.raise_for_status()
            return [
                {"id": t["name"], "capabilities": t.get("capabilities") or _guess_caps(t)}
                for t in r.json().get("models", []) if t.get("name")
            ]
        r = await client.get(provider.base_url.rstrip("/") + "/models", headers=provider.headers())
        r.raise_for_status()
        data = r.json().get("data", [])
        return [
            {"id": m["id"], "capabilities": _caps_from_remote_entry(m) or _guess_caps_from_name(m["id"])}
            for m in data if isinstance(m, dict) and m.get("id")
        ]


async def detect_model_caps(provider: Provider, real_name: str) -> list[str]:
    """添加模型未指定 capabilities 时：拉远端列表读该模型的能力字段，失败/查不到按族名兜底。"""
    try:
        entry = next((e for e in await fetch_remote_models(provider) if e["id"] == real_name), None)
        if entry:
            return entry["capabilities"]
    except Exception:
        pass
    return _guess_caps_from_name(real_name)


async def ping_model(model_id: str) -> int:
    """模型级测试：嵌入模型实际嵌入一次；对话模型测供应商连通（不消耗生成额度）。"""
    info = provider_store.model_info(model_id)
    provider, _ = await _resolve_or_raise(model_id)
    t0 = time.time()
    if info and info.get("capabilities") == ["embedding"]:
        await embed_texts(model_id, ["ping"])
        return int((time.time() - t0) * 1000)
    return await ping_provider(provider)


# ---------- Ollama 连接向导 ----------

async def probe_ollama(base_url: str) -> dict:
    """探测一个 Ollama 地址（只读不存）：{base_url, reachable, version, models, error}。"""
    base_url = base_url.strip().rstrip("/")
    out = {"base_url": base_url, "reachable": False, "version": None, "models": [], "error": None}
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_PROBE_TIMEOUT_S,
                                     trust_env=not _is_loopback(base_url)) as client:
            r = await client.get(f"{base_url}/api/version")
            r.raise_for_status()
            out["version"] = r.json().get("version")
            tags = (await client.get(f"{base_url}/api/tags")).json().get("models", [])
            out["models"] = [t["name"] for t in tags if t.get("name")]
            out["reachable"] = True
    except Exception as e:
        out["error"] = _short_error(e)
    return out


async def detect_ollama(base_url: str | None = None) -> dict:
    """自动检测：给了地址只测该地址；否则依次尝试当前配置地址与常见本机地址，返回第一个可达的。"""
    if base_url:
        return await probe_ollama(base_url)
    builtin = provider_store.get("ollama")
    candidates = [builtin.base_url] if builtin else []
    candidates += [u for u in OLLAMA_CANDIDATE_URLS if u not in candidates]
    first = None
    for url in candidates:
        res = await probe_ollama(url)
        if res["reachable"]:
            return res
        first = first or res
    return first


async def pull_model(provider: Provider, name: str) -> AsyncIterator[dict]:
    """代理 Ollama /api/pull：逐条 yield 进度 {status, completed?, total?}；失败抛 RuntimeError。"""
    if not MODEL_NAME_RE.match(name):
        raise RuntimeError(f"模型名不合法：{name}")
    # 下载大模型可能持续数十分钟：不设读超时，只限制连接超时
    timeout = httpx.Timeout(None, connect=OLLAMA_PROBE_TIMEOUT_S)
    async with httpx.AsyncClient(timeout=timeout, trust_env=not _is_loopback(provider.base_url)) as client:
        req = client.build_request("POST", f"{provider.base_url}/api/pull", json={"model": name, "stream": True})
        resp = await client.send(req, stream=True)
        try:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                raise RuntimeError(f"Ollama 返回 {resp.status_code}：{body}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    j = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if j.get("error"):
                    raise RuntimeError(j["error"])
                yield {k: j[k] for k in ("status", "completed", "total") if k in j}
        finally:
            await resp.aclose()

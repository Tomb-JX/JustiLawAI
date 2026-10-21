"""模型与供应商管理：模型注册表（含自定义 API 配置）+ 默认模型设置。

读接口所有登录用户可用；修改供应商 / 默认模型需要管理员（api_key 属于平台级配置）。
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..auth import current_user, require_admin
from ..model_gateway.gateway import (
    CAP_SET, detect_ollama, detect_model_caps, fetch_remote_models,
    ping_model, ping_provider, provider_store, pull_model,
)
from ..resp import err, ok

router = APIRouter(dependencies=[Depends(current_user)])

PROVIDER_TYPES = ("openai_compat", "ollama")


def _public(p) -> dict:
    """供应商公开信息；自动发现的供应商附带最近一次连接状态。"""
    out = p.public()
    if p.auto_discover:
        out["status"] = provider_store.status.get(p.id)
    return out


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/models")
async def list_models(capability: str | None = None):
    """capability：completion | embedding | vision | tools | thinking，可选过滤。"""
    return ok(provider_store.all_models(capability))


@router.post("/models/{model_id:path}/ping")
async def ping_model_api(model_id: str):
    if not provider_store.resolve(model_id):
        raise HTTPException(404, detail=err(40400, "模型不存在"))
    try:
        return ok({"latency_ms": await ping_model(model_id)})
    except Exception as e:
        raise HTTPException(500, detail=err(50001, f"连通失败：{e}"))


# ---------- 默认模型 ----------

@router.get("/settings/models")
async def get_model_settings():
    return ok({
        "default_chat_model": provider_store.default_model("chat"),
        "default_embed_model": provider_store.default_model("embedding"),
    })


@router.put("/settings/models", dependencies=[Depends(require_admin)])
async def set_model_settings(body: dict):
    for key, kind in (("default_chat_model", "chat"), ("default_embed_model", "embedding")):
        if body.get(key) and not provider_store.set_default_model(kind, body[key]):
            label = "对话" if kind == "chat" else "嵌入"
            raise HTTPException(422, detail=err(42200, f"{body[key]} 不是可用的{label}模型"))
    return await get_model_settings()


# ---------- 供应商（自定义 API 模块，对齐主流智能体平台） ----------

@router.get("/providers")
async def list_providers():
    return ok([_public(p) for p in provider_store.list()])


@router.post("/providers/ollama/detect", dependencies=[Depends(require_admin)])
async def detect_ollama_api(body: dict | None = None):
    """检测 Ollama 是否可达（只测不存）。不传 base_url 时依次尝试当前地址与常见本机地址。"""
    return ok(await detect_ollama((body or {}).get("base_url")))


@router.post("/providers", dependencies=[Depends(require_admin)])
async def add_provider(body: dict):
    if not body.get("name") or not body.get("base_url"):
        raise HTTPException(422, detail=err(42200, "name 与 base_url 必填"))
    ptype = body.get("type") or "openai_compat"
    if ptype not in PROVIDER_TYPES:
        raise HTTPException(422, detail=err(42200, f"type 只能是 {' / '.join(PROVIDER_TYPES)}"))
    base_url = body["base_url"].strip().rstrip("/")
    for suffix in ("/chat/completions", "/embeddings"):  # 用户常把完整接口地址粘进来
        base_url = base_url.removesuffix(suffix)
    p = provider_store.add(
        name=body["name"].strip(),
        type=ptype,
        base_url=base_url,
        api_key=(body.get("api_key") or "").strip(),
        enabled=body.get("enabled", True),
    )
    if p.auto_discover:
        await provider_store.refresh_async(p.id)
    return ok(_public(p))


@router.patch("/providers/{pid}", dependencies=[Depends(require_admin)])
async def update_provider(pid: str, body: dict):
    # api_key 打码回传时不覆盖原值
    if str(body.get("api_key") or "").startswith("****"):
        body["api_key"] = None
    p = provider_store.update(pid, body)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    if p.auto_discover and not p.models:  # 改了地址：立即按新地址重新发现
        await provider_store.refresh_async(pid)
    return ok(_public(p))


@router.delete("/providers/{pid}", dependencies=[Depends(require_admin)])
async def delete_provider(pid: str):
    if not provider_store.delete(pid):
        raise HTTPException(400, detail=err(40000, "内置供应商不可删除或不存在"))
    return ok(None)


@router.post("/providers/{pid}/ping")
async def ping_provider_api(pid: str):
    p = provider_store.get(pid)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    try:
        return ok({"latency_ms": await ping_provider(p)})
    except Exception as e:
        raise HTTPException(500, detail=err(50001, f"连通失败：{e}"))


@router.post("/providers/{pid}/remote-models", dependencies=[Depends(require_admin)])
async def list_remote_models(pid: str):
    """拉取远端供应商的模型名列表（只列不存，供「添加模型」点选）。"""
    p = provider_store.get(pid)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    try:
        return ok({"models": await fetch_remote_models(p)})
    except Exception as e:
        raise HTTPException(500, detail=err(50001, f"拉取模型列表失败：{e}"))


@router.post("/providers/{pid}/refresh", dependencies=[Depends(require_admin)])
async def refresh_provider(pid: str):
    """重新发现模型（Ollama 新 pull 的模型立即可见）。"""
    p = provider_store.get(pid)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    if not p.auto_discover:
        raise HTTPException(400, detail=err(40000, "该供应商的模型需要手动添加"))
    if not await provider_store.refresh_async(pid):
        reason = (provider_store.status.get(pid) or {}).get("error") or "无法连接"
        raise HTTPException(500, detail=err(50001, f"{reason}：{p.base_url}"))
    return ok(_public(p))


@router.post("/providers/{pid}/pull", dependencies=[Depends(require_admin)])
async def pull_provider_model(pid: str, body: dict):
    """让 Ollama 下载模型，SSE 推送进度：progress {status, completed?, total?} → done {model} | error。

    下载完成后刷新模型清单；平台此前没有同类模型时，自动设为默认对话 / 嵌入模型。
    客户端断开不会中止 Ollama 端的下载（再次拉取会断点续传）。
    """
    p = provider_store.get(pid)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    if p.type != "ollama":
        raise HTTPException(400, detail=err(40000, "只有 Ollama 供应商支持在线拉取模型"))
    name = (body.get("model") or "").strip()
    if not name:
        raise HTTPException(422, detail=err(42200, "model 必填"))
    had_chat = bool(provider_store.all_models("completion"))
    had_embed = bool(provider_store.all_models("embedding"))

    async def gen():
        try:
            async for prog in pull_model(p, name):
                yield _sse("progress", prog)
            await provider_store.refresh_async(pid)
            mid = next((m["id"] for m in p.models if m["name"] in (name, f"{name}:latest")), f"{pid}/{name}")
            if not had_chat:
                provider_store.set_default_model("chat", mid)
            if not had_embed:
                provider_store.set_default_model("embedding", mid)
            yield _sse("done", {"model": mid})
        except Exception as e:
            yield _sse("error", {"code": 50001, "message": f"拉取失败：{e}"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/providers/{pid}/models", dependencies=[Depends(require_admin)])
async def add_provider_model(pid: str, body: dict):
    mid = (body.get("id") or body.get("name") or "").strip()
    if not mid:
        raise HTTPException(422, detail=err(42200, "模型名必填"))
    p = provider_store.get(pid)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    caps = body.get("capabilities")
    if not caps:  # 未指定：直接读取模型服务返回的能力字段，用户无需手动填写
        caps = await detect_model_caps(p, mid)
    unknown = set(caps) - CAP_SET
    if unknown:
        raise HTTPException(422, detail=err(42200, f"未知能力标签：{', '.join(sorted(unknown))}"))
    m = provider_store.add_model(pid, {**body, "id": mid, "name": (body.get("name") or mid).strip(),
                                       "capabilities": caps})
    return ok(m)


@router.patch("/providers/{pid}/models/{model_id:path}", dependencies=[Depends(require_admin)])
async def update_provider_model(pid: str, model_id: str, body: dict):
    m = provider_store.update_model(pid, model_id, body)
    if not m:
        raise HTTPException(404, detail=err(40400, "模型不存在"))
    return ok(m)


@router.delete("/providers/{pid}/models/{model_id:path}", dependencies=[Depends(require_admin)])
async def remove_provider_model(pid: str, model_id: str):
    if not provider_store.remove_model(pid, model_id):
        raise HTTPException(404, detail=err(40400, "模型不存在"))
    return ok(None)

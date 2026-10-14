"""模型与供应商管理：模型注册表（含自定义 API 配置）+ 默认模型设置。

读接口所有登录用户可用；修改供应商 / 默认模型需要管理员（api_key 属于平台级配置）。
"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import current_user, require_admin
from ..model_gateway.gateway import ping_model, ping_provider, provider_store
from ..resp import err, ok

router = APIRouter(dependencies=[Depends(current_user)])

PROVIDER_TYPES = ("openai_compat", "ollama")


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
    return ok([p.public() for p in provider_store.list()])


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
    return ok(p.public())


@router.patch("/providers/{pid}", dependencies=[Depends(require_admin)])
async def update_provider(pid: str, body: dict):
    # api_key 打码回传时不覆盖原值
    if str(body.get("api_key") or "").startswith("****"):
        body["api_key"] = None
    p = provider_store.update(pid, body)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    return ok(p.public())


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


@router.post("/providers/{pid}/refresh", dependencies=[Depends(require_admin)])
async def refresh_provider(pid: str):
    """重新发现模型（Ollama 新 pull 的模型立即可见）。"""
    p = provider_store.get(pid)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    if not p.auto_discover:
        raise HTTPException(400, detail=err(40000, "该供应商的模型需要手动添加"))
    if not provider_store.refresh(pid):
        raise HTTPException(500, detail=err(50001, f"无法连接 {p.base_url}"))
    return ok(p.public())


@router.post("/providers/{pid}/models", dependencies=[Depends(require_admin)])
async def add_provider_model(pid: str, body: dict):
    mid = (body.get("id") or body.get("name") or "").strip()
    if not mid:
        raise HTTPException(422, detail=err(42200, "模型名必填"))
    caps = body.get("capabilities") or ["completion"]
    unknown = set(caps) - {"completion", "embedding", "vision", "tools", "thinking"}
    if unknown:
        raise HTTPException(422, detail=err(42200, f"未知能力标签：{', '.join(sorted(unknown))}"))
    m = provider_store.add_model(pid, {**body, "id": mid, "name": (body.get("name") or mid).strip(),
                                       "capabilities": caps})
    if not m:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
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

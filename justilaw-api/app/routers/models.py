"""模型与供应商管理：模型注册表（含自定义 API 配置）。"""
from fastapi import APIRouter, HTTPException

from ..model_gateway.gateway import ping_provider, provider_store
from ..resp import err, ok
from ..store import uid

router = APIRouter()


@router.get("/models")
async def list_models():
    return ok(provider_store.all_models())


@router.post("/models/{model_id:path}/ping")
async def ping_model(model_id: str):
    resolved = provider_store.resolve(model_id)
    if not resolved:
        raise HTTPException(404, detail=err(40400, "模型不存在"))
    provider, _ = resolved
    try:
        latency = await ping_provider(provider)
        return ok({"latency_ms": latency})
    except Exception as e:
        raise HTTPException(500, detail=err(50001, f"连通失败：{e}"))


# ---------- 供应商（自定义 API 模块，对齐主流智能体平台） ----------

@router.get("/providers")
async def list_providers():
    return ok([p.public() for p in provider_store.list()])


@router.post("/providers")
async def add_provider(body: dict):
    if not body.get("name") or not body.get("base_url"):
        raise HTTPException(422, detail=err(42200, "name 与 base_url 必填"))
    p = provider_store.add(
        name=body["name"],
        base_url=body["base_url"].rstrip("/").removesuffix("/chat/completions"),
        api_key=body.get("api_key", ""),
        enabled=body.get("enabled", True),
    )
    return ok(p.public())


@router.patch("/providers/{pid}")
async def update_provider(pid: str, body: dict):
    # api_key 打码回传时不覆盖原值
    if body.get("api_key", "").startswith("****"):
        body["api_key"] = None
    p = provider_store.update(pid, body)
    if not p:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    return ok(p.public())


@router.delete("/providers/{pid}")
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
        latency = await ping_provider(p)
        return ok({"latency_ms": latency})
    except Exception as e:
        raise HTTPException(500, detail=err(50001, f"连通失败：{e}"))


@router.post("/providers/{pid}/models")
async def add_provider_model(pid: str, body: dict):
    if not body.get("id") and not body.get("name"):
        raise HTTPException(422, detail=err(42200, "模型名必填"))
    body["id"] = body.get("id") or body["name"]
    body["name"] = body.get("name") or body["id"]
    m = provider_store.add_model(pid, body)
    if not m:
        raise HTTPException(404, detail=err(40400, "供应商不存在"))
    return ok(m)


@router.delete("/providers/{pid}/models/{model_id:path}")
async def remove_provider_model(pid: str, model_id: str):
    if not provider_store.remove_model(pid, model_id):
        raise HTTPException(404, detail=err(40400, "模型不存在"))
    return ok(None)

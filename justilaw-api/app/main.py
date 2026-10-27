"""JustiLawAI 模型服务 FastAPI 入口。

启动：cd justilaw-api && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
"""
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .auth import AUTH_ENABLED
from .model_gateway.gateway import provider_store
from .resp import err
from .routers import chat, conversations, datasets, discretion, files, misc, models, workflows
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("justilaw")

app = FastAPI(title="JustiLawAI Model API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 统一错误包：始终返回 { code, message, data }（契约 §1.1） ----------

@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    body = exc.detail if isinstance(exc.detail, dict) and "code" in exc.detail \
        else err(exc.status_code * 100, str(exc.detail))
    return JSONResponse(body, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    detail = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in exc.errors())
    return JSONResponse(err(42200, f"参数校验失败：{detail}"), status_code=422)


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    log.exception("未处理异常")
    return JSONResponse(err(50000, f"服务器内部错误：{exc}"), status_code=500)


for r in (models, chat, conversations, datasets, files, workflows, misc, discretion):
    app.include_router(r.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    chat_model = provider_store.default_model("chat")
    embed_model = provider_store.default_model("embedding")
    ollama = provider_store.get("ollama")
    status = provider_store.status.get("ollama") or {}
    warnings = []
    if ollama and ollama.enabled and status.get("reachable") is False:
        warnings.append(f"Ollama 连接失败：{status.get('error')}")
    if not chat_model:
        warnings.append("没有可用的对话模型")
    if not embed_model:
        warnings.append("没有可用的嵌入模型，知识库无法入库与检索（可执行 ollama pull bge-m3）")
    return {"code": 0, "message": "ok", "data": {
        "service": "justilaw-api", "status": "up" if not warnings else "degraded",
        "auth_enabled": AUTH_ENABLED,
        # 前端据此决定是否展示「模型连接向导」
        "setup_required": not chat_model,
        "ollama": {
            "enabled": bool(ollama and ollama.enabled),
            "reachable": status.get("reachable"),     # None = 尚未检测
            "version": status.get("version"),
            # 公网部署不暴露内网地址；单机模式下向导需要显示它
            "base_url": None if AUTH_ENABLED else (ollama.base_url if ollama else None),
        },
        "default_chat_model": chat_model, "default_embed_model": embed_model,
        "warnings": warnings,
    }}


@app.on_event("startup")
async def startup_refresh_models():
    """后台发现 Ollama 模型：Ollama 未启动时服务照常启动，不在这里等待。"""
    asyncio.create_task(provider_store.refresh_all())


@app.on_event("startup")
async def startup_warm():
    """启动时与每小时预热 JWKS 缓存：避免新 kid token 的首个请求在线拉取（网络不稳会卡 5s）。"""
    if not AUTH_ENABLED:
        return

    from .auth import warm_jwks

    async def loop():
        while True:
            await asyncio.to_thread(warm_jwks)
            await asyncio.sleep(3600)

    asyncio.create_task(loop())


# ---------- 托管前端（本地一键部署：一个端口同时提供网页与 API） ----------

if (config.WEB_DIST_DIR / "index.html").exists():
    _web_root = config.WEB_DIST_DIR.resolve()
    log.info("托管前端：%s", _web_root)

    @app.get("/{path:path}", include_in_schema=False)
    async def web(path: str):
        if path.startswith("api/"):  # 未匹配的 API 路径仍返回 JSON 404，不能回退成网页
            return JSONResponse(err(40400, "接口不存在"), status_code=404)
        target = (_web_root / path).resolve()
        if path and target.is_file() and target.is_relative_to(_web_root):
            # 带 hash 的静态资源可长期缓存；index.html 每次校验，保证部署更新后拿到新版本
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        if path.startswith("assets/"):  # 旧版本的 chunk 已不存在：返回 404 让前端触发整页刷新
            return JSONResponse(err(40400, "资源不存在"), status_code=404)
        return FileResponse(_web_root / "index.html", headers={"Cache-Control": "no-cache"})


seed()

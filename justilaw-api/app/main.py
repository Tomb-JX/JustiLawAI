"""JustiLawAI 模型服务 FastAPI 入口。

启动：cd justilaw-api && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .auth import AUTH_ENABLED
from .model_gateway.gateway import provider_store
from .resp import err
from .routers import chat, conversations, datasets, files, misc, models, workflows
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


for r in (models, chat, conversations, datasets, files, workflows, misc):
    app.include_router(r.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    chat_model = provider_store.default_model("chat")
    embed_model = provider_store.default_model("embedding")
    warnings = []
    if not chat_model:
        warnings.append("没有可用的对话模型")
    if not embed_model:
        warnings.append("没有可用的嵌入模型，知识库无法入库与检索（可执行 ollama pull bge-m3）")
    return {"code": 0, "message": "ok", "data": {
        "service": "justilaw-api", "status": "up" if not warnings else "degraded",
        "auth_enabled": AUTH_ENABLED,
        "default_chat_model": chat_model, "default_embed_model": embed_model,
        "warnings": warnings,
    }}


seed()

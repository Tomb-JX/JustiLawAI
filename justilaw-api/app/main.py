"""JustiLawAI 模型服务 FastAPI 入口。

启动：cd justilaw-api && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import chat, conversations, datasets, models, misc
from .seed import seed

app = FastAPI(title="JustiLawAI Model API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(models.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(datasets.router, prefix="/api/v1")
app.include_router(misc.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"code": 0, "message": "ok", "data": {"service": "justilaw-api", "status": "up"}}


seed()

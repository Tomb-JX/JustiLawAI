"""JustiLawAI 模型服务后端配置。

所有项均可用同名环境变量覆盖（本地覆盖可写在 justilaw-api/.env，不入库）。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# 服务
API_HOST = _env("API_HOST", "127.0.0.1")
API_PORT = int(_env("API_PORT", "8000"))
CORS_ORIGINS = [o.strip() for o in _env(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
).split(",") if o.strip()]

# Ollama（不读系统 OLLAMA_HOST：它常被设为 0.0.0.0 这类监听地址，不能用来连接）
OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

# 默认模型（平台模型 ID）。「模型服务」页可修改，持久化在 store/settings.json 并优先于此处
DEFAULT_CHAT_MODEL = _env("DEFAULT_CHAT_MODEL", "ollama/qwen3.5:9b")
DEFAULT_EMBED_MODEL = _env("DEFAULT_EMBED_MODEL", "ollama/bge-m3")

# 鉴权（Logto OIDC，见 docs/02-design/api-contract.md §1.3）。
# LOGTO_ENDPOINT 配置即启用鉴权：优先 resource 模式（LOGTO_API_RESOURCE，Pro 功能）；
# 免费版用 idtoken 模式（LOGTO_APP_ID）：前端直传 ID Token，按 aud=client_id 校验。
LOGTO_ENDPOINT = _env("LOGTO_ENDPOINT", "").rstrip("/")
LOGTO_API_RESOURCE = _env("LOGTO_API_RESOURCE", "")
LOGTO_APP_ID = _env("LOGTO_APP_ID", "")
# 逗号分隔的 Logto 用户 ID（sub），视为管理员
ADMIN_SUBS = {s.strip() for s in _env("ADMIN_SUBS", "").split(",") if s.strip()}

# 数据持久化（JSON，演示规模足够；后续可换 SQLite/PG）
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "store")))
UPLOAD_DIR = DATA_DIR / "uploads"
VECTORS_DIR = DATA_DIR / "vectors"

# RAG 默认参数（与前端契约一致）
CHUNK_MAX_LENGTH = 500
CHUNK_OVERLAP = 50
RETRIEVAL_TOP_K = 5
RETRIEVAL_SCORE_THRESHOLD = 0.35

# 模型推理
LLM_TIMEOUT_S = 300          # 单次生成超时
EMBED_BATCH_SIZE = 16         # 嵌入批次大小
MAX_UPLOAD_MB = 20
ATTACHMENT_MAX_CHARS = 8000   # 单个对话附件注入上下文的最大字数
HTTP_NODE_TIMEOUT_S = 20      # 工作流 HTTP 节点超时

for d in (DATA_DIR, UPLOAD_DIR, VECTORS_DIR):
    d.mkdir(parents=True, exist_ok=True)

"""JustiLawAI 模型服务后端配置"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 服务
API_HOST = "127.0.0.1"
API_PORT = 8000

# Ollama
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

# 默认模型策略
DEFAULT_CHAT_MODEL = "qwen3.5:9b"          # 本地主力对话模型
DEFAULT_EMBED_MODEL = "bge-m3"             # 中文法律文本嵌入模型

# 数据持久化（JSON，演示规模足够；后续可换 SQLite/PG）
DATA_DIR = BASE_DIR / "store"
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

for d in (DATA_DIR, UPLOAD_DIR, VECTORS_DIR):
    d.mkdir(parents=True, exist_ok=True)

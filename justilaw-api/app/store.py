"""业务数据持久化：会话/消息/智能体/知识库/文档/提示词/工作流/统计。

JSON 文件存储，进程内单例；写操作直接落盘（演示规模够用，后续可平滑换 SQLite）。
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

LOCK = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class JsonDB:
    def __init__(self, name: str, default):
        self.path = config.DATA_DIR / f"{name}.json"
        self.data = default
        if self.path.exists():
            self.data = json.loads(self.path.read_text("utf-8"))

    def save(self):
        with LOCK:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")


# 各业务集合
conversations_db = JsonDB("conversations", [])            # list[Conversation]
messages_db = JsonDB("messages", {})                       # {conversation_id: list[Message]}
agents_db = JsonDB("agents", [])                           # list[Agent]
datasets_db = JsonDB("datasets", [])                       # list[Dataset]
documents_db = JsonDB("documents", [])                     # list[Document]
chunks_db = JsonDB("chunks", {})                           # {document_id: list[Chunk]}
prompts_db = JsonDB("prompts", [])                         # list[Prompt]
workflows_db = JsonDB("workflows", [])                     # list[Workflow]
stats_db = JsonDB("stats", {"daily_calls": {}, "model_calls": {}})  # 统计


def record_call(model_id: str):
    """记录一次模型调用（按日/按模型）。"""
    day = datetime.now().strftime("%m-%d")
    stats_db.data["daily_calls"][day] = stats_db.data["daily_calls"].get(day, 0) + 1
    stats_db.data["model_calls"][model_id] = stats_db.data["model_calls"].get(model_id, 0) + 1
    stats_db.save()


# ---------- 通用查找 ----------

def find(collection: list[dict], **kw):
    for item in collection:
        if all(item.get(k) == v for k, v in kw.items()):
            return item
    return None


def save_upload(file_bytes: bytes, filename: str) -> Path:
    dest = config.UPLOAD_DIR / f"{uid('f')}_{Path(filename).name}"
    dest.write_bytes(file_bytes)
    return dest

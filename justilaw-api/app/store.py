"""业务数据持久化：会话/消息/智能体/知识库/文档/提示词/工作流/用户/文件/统计。

JSON 文件存储，进程内单例；写操作直接落盘（演示规模够用，后续可平滑换 SQLite）。
"""
from __future__ import annotations

import json
import os
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
        # 先写临时文件再替换：进程中途被杀也不会留下半截 JSON
        with LOCK:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
            os.replace(tmp, self.path)


# 各业务集合
conversations_db = JsonDB("conversations", [])            # list[Conversation]
messages_db = JsonDB("messages", {})                       # {conversation_id: list[Message]}
agents_db = JsonDB("agents", [])                           # list[Agent]
datasets_db = JsonDB("datasets", [])                       # list[Dataset]
documents_db = JsonDB("documents", [])                     # list[Document]
chunks_db = JsonDB("chunks", {})                           # {document_id: list[Chunk]}
prompts_db = JsonDB("prompts", [])                         # list[Prompt]
workflows_db = JsonDB("workflows", [])                     # list[Workflow]
users_db = JsonDB("users", [])                             # list[User]
files_db = JsonDB("files", {})                             # {file_id: {filename, size, path, owner}}
settings_db = JsonDB("settings", {})                       # 平台设置（默认模型等）
stats_db = JsonDB("stats", {"daily_calls": {}, "model_calls": {}})  # 统计
discretion_runs_db = JsonDB("discretion_runs", {})         # {run_id: 裁量运行存档（请求摘要、结果、trace）}


def record_call(model_id: str, usage: dict | None = None):
    """记录一次模型调用（按日/按模型，含 token 用量）。"""
    day = datetime.now().strftime("%m-%d")
    s = stats_db.data
    s["daily_calls"][day] = s["daily_calls"].get(day, 0) + 1
    s["model_calls"][model_id] = s["model_calls"].get(model_id, 0) + 1
    if usage:
        tokens = s.setdefault("tokens", {})
        tokens[model_id] = (tokens.get(model_id, 0)
                            + usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
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

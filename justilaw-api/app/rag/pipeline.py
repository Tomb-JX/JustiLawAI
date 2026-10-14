"""RAG 管线：文件解析 → 分段切分 → 嵌入 → 向量检索。

解析器支持：PDF / DOCX / TXT / Markdown / JSON（CAIL 数据）。
向量库：numpy 余弦相似度 + npz 持久化（演示规模：万级分段毫秒级检索）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config


# ---------- 解析 ----------

def parse_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        import docx

        d = docx.Document(str(path))
        return "\n".join(p.text for p in d.paragraphs)
    if suffix == ".json":
        raw = json.loads(path.read_text("utf-8"))
        if isinstance(raw, list):  # CAIL 案例数组：抽取事实/罪名等关键字段
            parts = []
            for i, item in enumerate(raw[:5000]):
                fact = item.get("fact") or item.get("content") or json.dumps(item, ensure_ascii=False)
                meta = {k: item[k] for k in ("accusation", "articles", "meta") if k in item}
                parts.append(f"【案例{i}】{fact}\n罪名/要素：{json.dumps(meta, ensure_ascii=False)}")
            return "\n\n".join(parts)
        return json.dumps(raw, ensure_ascii=False)
    # txt / md / 其他纯文本
    return path.read_text("utf-8", errors="ignore")


# ---------- 切分（定长 + 重叠，参数对齐前端契约） ----------

def chunk_text(text: str, max_length: int = config.CHUNK_MAX_LENGTH, overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # 优先按段落/换行聚合到目标长度，超长段落再硬切
    chunks: list[str] = []
    cur = ""
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        if len(cur) + len(para) + 1 <= max_length:
            cur = f"{cur}\n{para}".strip()
        else:
            if cur:
                chunks.append(cur)
            while len(para) > max_length:  # 硬切超长段落
                chunks.append(para[:max_length])
                para = para[max_length - overlap :] if overlap > 0 else para[max_length:]
            cur = para
    if cur:
        chunks.append(cur)
    return chunks


# ---------- 向量库 ----------

@dataclass
class Hit:
    chunk_id: str
    content: str
    score: float
    doc_id: str
    index: int

class VectorStore:
    """按知识库分区存储：vectors/<dataset_id>.npz + <dataset_id>.meta.json"""

    def __init__(self, dataset_id: str):
        self.dataset_id = dataset_id
        self.vec_path = config.VECTORS_DIR / f"{dataset_id}.npz"
        self.meta_path = config.VECTORS_DIR / f"{dataset_id}.meta.json"
        self._vectors: np.ndarray | None = None
        self._meta: list[dict] = []

    def _load(self):
        if self._vectors is not None:
            return
        if self.vec_path.exists() and self.meta_path.exists():
            self._vectors = np.load(self.vec_path)["v"]
            self._meta = json.loads(self.meta_path.read_text("utf-8"))
        else:
            self._vectors = np.empty((0, 0), dtype=np.float32)
            self._meta = []

    def _save(self):
        np.savez_compressed(self.vec_path, v=self._vectors)
        self.meta_path.write_text(json.dumps(self._meta, ensure_ascii=False), "utf-8")

    def size(self) -> int:
        self._load()
        return len(self._meta)

    def add(self, embed_model: str, entries: list[dict], vectors: list[list[float]]):
        """entries: [{chunk_id, doc_id, index, content}]"""
        self._load()
        arr = np.asarray(vectors, dtype=np.float32)
        # 归一化后点积即余弦
        arr = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)
        self._vectors = arr if self._vectors.size == 0 else np.vstack([self._vectors, arr])
        for e, _ in zip(entries, vectors):
            self._meta.append({**e, "embed_model": embed_model})
        self._save()

    def remove_doc(self, doc_id: str):
        self._load()
        keep = [i for i, m in enumerate(self._meta) if m["doc_id"] != doc_id]
        self._meta = [self._meta[i] for i in keep]
        self._vectors = self._vectors[keep] if self._vectors.size else self._vectors
        self._save()

    def search(self, query_vec: list[float], top_k: int, threshold: float) -> list[Hit]:
        self._load()
        if self._vectors.size == 0 or not self._meta:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-10)
        scores = self._vectors @ q
        order = np.argsort(-scores)[: top_k * 2]  # 多取一倍，过滤阈值后再截断
        hits = [
            Hit(
                chunk_id=self._meta[i]["chunk_id"],
                content=self._meta[i]["content"],
                score=float(scores[i]),
                doc_id=self._meta[i]["doc_id"],
                index=self._meta[i]["index"],
            )
            for i in order
            if scores[i] >= threshold
        ]
        return hits[:top_k]

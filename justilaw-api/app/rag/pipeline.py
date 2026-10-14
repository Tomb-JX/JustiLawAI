"""RAG 管线：文件解析 → 分段切分 → 嵌入 → 向量检索。

解析器支持：PDF / DOCX（含表格）/ TXT / Markdown / JSON（CAIL 数据）。
向量库：numpy 余弦相似度 + npz 持久化（演示规模：万级分段毫秒级检索）。
每个知识库固定一个嵌入模型（不同模型的向量维度与空间不可混用）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown", ".json", ".csv"}


class UnsupportedFileError(ValueError):
    pass


# ---------- 解析 ----------

def parse_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".doc":
        raise UnsupportedFileError("暂不支持旧版 .doc，请用 Word / WPS 另存为 .docx 后上传")
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileError(f"不支持的文件类型 {suffix}，支持：{'、'.join(sorted(SUPPORTED_SUFFIXES))}")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise UnsupportedFileError("PDF 中没有可提取的文字（可能是扫描件，需要先做 OCR）")
        return text
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix == ".json":
        raw = json.loads(path.read_text("utf-8"))
        if isinstance(raw, list):  # CAIL 案例数组：抽取事实/罪名等关键字段
            parts = []
            for i, item in enumerate(raw[:5000]):
                if not isinstance(item, dict):
                    parts.append(str(item))
                    continue
                fact = item.get("fact") or item.get("content") or json.dumps(item, ensure_ascii=False)
                meta = {k: item[k] for k in ("accusation", "articles", "meta") if k in item}
                parts.append(f"【案例{i}】{fact}\n罪名/要素：{json.dumps(meta, ensure_ascii=False)}")
            return "\n\n".join(parts)
        return json.dumps(raw, ensure_ascii=False, indent=1)
    # txt / md / csv
    return _read_text(path)


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "gb18030"):  # 国内文本常见 GBK 编码
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _parse_docx(path: Path) -> str:
    """按文档顺序输出段落与表格（判决书、处罚决定书常用表格排版）。"""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    lines: list[str] = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(Paragraph(child, d).text)
        elif tag == "tbl":
            for row in Table(child, d).rows:
                cells = []
                for c in row.cells:  # 合并单元格会重复出现，去重保持顺序
                    t = c.text.strip()
                    if t and (not cells or cells[-1] != t):
                        cells.append(t)
                if cells:
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


# ---------- 切分（段落聚合 + 超长硬切 + 重叠，参数对齐前端契约） ----------

def chunk_text(text: str, max_length: int = config.CHUNK_MAX_LENGTH, overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    overlap = max(0, min(overlap, max_length // 2))
    chunks: list[str] = []
    cur = ""
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        if len(cur) + len(para) + 1 <= max_length:
            cur = f"{cur}\n{para}".strip()
            continue
        if cur:
            chunks.append(cur)
        while len(para) > max_length:  # 硬切超长段落
            chunks.append(para[:max_length])
            para = para[max_length - overlap:]
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

    @staticmethod
    def _normalize(vectors) -> np.ndarray:
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr[None, :]
        # 归一化后点积即余弦
        return arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)

    def size(self) -> int:
        self._load()
        return len(self._meta)

    def add(self, embed_model: str, entries: list[dict], vectors: list[list[float]]):
        """entries: [{chunk_id, doc_id, index, content}]"""
        self._load()
        arr = self._normalize(vectors)
        if self._vectors.size and self._vectors.shape[1] != arr.shape[1]:
            raise RuntimeError(
                f"向量维度不一致（库内 {self._vectors.shape[1]}，新增 {arr.shape[1]}）："
                "知识库已用其他嵌入模型建立，请重建索引")
        self._vectors = arr if self._vectors.size == 0 else np.vstack([self._vectors, arr])
        for e in entries:
            self._meta.append({**e, "embed_model": embed_model, "enabled": e.get("enabled", True)})
        self._save()

    def update_chunk(self, chunk_id: str, *, enabled: bool | None = None,
                     content: str | None = None, vector: list[float] | None = None) -> bool:
        self._load()
        for i, m in enumerate(self._meta):
            if m["chunk_id"] != chunk_id:
                continue
            if enabled is not None:
                m["enabled"] = enabled
            if content is not None:
                m["content"] = content
            if vector is not None:
                self._vectors[i] = self._normalize(vector)[0]
            self._save()
            return True
        return False

    def remove_doc(self, doc_id: str):
        self._load()
        keep = [i for i, m in enumerate(self._meta) if m["doc_id"] != doc_id]
        self._meta = [self._meta[i] for i in keep]
        self._vectors = self._vectors[keep] if self._vectors.size and keep else np.empty((0, 0), dtype=np.float32)
        self._save()

    def clear(self):
        self.vec_path.unlink(missing_ok=True)
        self.meta_path.unlink(missing_ok=True)
        self._vectors, self._meta = None, []

    def search(self, query_vec: list[float], top_k: int, threshold: float) -> list[Hit]:
        self._load()
        if self._vectors.size == 0 or not self._meta:
            return []
        q = self._normalize(query_vec)[0]
        if q.shape[0] != self._vectors.shape[1]:
            raise RuntimeError("查询向量维度与知识库不一致：检索用的嵌入模型与建库时不同")
        scores = self._vectors @ q
        hits = []
        for i in np.argsort(-scores):
            if scores[i] < threshold or len(hits) >= top_k:
                break
            m = self._meta[i]
            if not m.get("enabled", True):
                continue
            hits.append(Hit(chunk_id=m["chunk_id"], content=m["content"], score=float(scores[i]),
                            doc_id=m["doc_id"], index=m["index"]))
        return hits

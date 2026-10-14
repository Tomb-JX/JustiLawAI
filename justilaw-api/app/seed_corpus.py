"""语料批量导入：把本地文件经真实 RAG 管线（解析 → 切分 → 嵌入 → 入库）导入知识库。

用法（在 justilaw-api 目录下）：
  python -m app.seed_corpus <文件或目录> <dataset_id>
例：
  python -m app.seed_corpus ../语料/法规 d_seed_law
  python -m app.seed_corpus 处罚决定书汇编.docx d_seed_case

只导入有出处的真实材料（法规原文、公开的处罚决定书 / 裁判文书）。
不要内置手写的"示例案例"：检索结果会被当作类案引用。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.model_gateway.gateway import embed_texts
from app.rag.pipeline import SUPPORTED_SUFFIXES, VectorStore, chunk_text, parse_file
from app.rag.retrieval import dataset_embed_model
from app.store import chunks_db, datasets_db, documents_db, find, now, uid


async def ingest_file(dataset_id: str, path: Path):
    ds = find(datasets_db.data, id=dataset_id)
    if not ds:
        raise SystemExit(f"知识库 {dataset_id} 不存在")
    text = parse_file(path)
    chunks = chunk_text(text, ds["chunk_config"]["max_length"], ds["chunk_config"]["overlap"])
    if not chunks:
        print(f"[skip] {path.name}：没有可提取的文本")
        return
    model = dataset_embed_model(ds)
    print(f"[ingest] {path.name}: {len(chunks)} 个分段，使用 {model} 嵌入中…")
    vectors = await embed_texts(model, chunks)
    doc = {"id": uid("doc"), "dataset_id": dataset_id, "filename": path.name,
           "size": path.stat().st_size, "status": "completed", "chunk_count": len(chunks),
           "created_by": "u_system", "created_at": now()}
    entries = [{"chunk_id": uid("ch"), "doc_id": doc["id"], "index": i + 1, "content": c}
               for i, c in enumerate(chunks)]
    VectorStore(dataset_id).add(model, entries, vectors)
    documents_db.data.insert(0, doc)
    chunks_db.data[doc["id"]] = [{**e, "enabled": True} for e in entries]
    ds["embed_model"] = model
    ds["doc_count"] = sum(1 for d in documents_db.data if d["dataset_id"] == dataset_id)
    for db in (documents_db, chunks_db, datasets_db):
        db.save()
    print(f"[done] {path.name} → {len(chunks)} 段已入库（{dataset_id}）")


async def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    target, dataset_id = Path(sys.argv[1]), sys.argv[2]
    files = sorted(p for p in target.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES) \
        if target.is_dir() else [target]
    for f in files:
        try:
            await ingest_file(dataset_id, f)
        except Exception as e:
            print(f"[fail] {f.name}：{e}")


if __name__ == "__main__":
    asyncio.run(main())

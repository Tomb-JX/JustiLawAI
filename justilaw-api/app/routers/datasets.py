"""知识库：dataset / document / chunk / hit-testing（真实 RAG 管线）。

上传 → 后台任务：解析 → 切分 → 嵌入(bge-m3) → 向量入库；状态轮询对齐契约。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks

from .. import config
from ..model_gateway.gateway import embed_texts
from ..rag.pipeline import VectorStore, chunk_text, parse_file
from ..resp import err, ok
from ..store import (chunks_db, datasets_db, documents_db, find, now, save_upload, uid)

router = APIRouter()

EMBED_MODEL = f"ollama/{config.DEFAULT_EMBED_MODEL}"


# ---------- 知识库 ----------

@router.get("/datasets")
async def list_datasets():
    return ok(datasets_db.data)


@router.post("/datasets")
async def create_dataset(body: dict):
    ds = {
        "id": uid("d"),
        "name": body.get("name", "未命名知识库"),
        "description": body.get("description"),
        "chunk_config": body.get("chunk_config") or {"max_length": config.CHUNK_MAX_LENGTH, "overlap": config.CHUNK_OVERLAP},
        "retrieval_config": body.get("retrieval_config") or {"top_k": config.RETRIEVAL_TOP_K, "score_threshold": config.RETRIEVAL_SCORE_THRESHOLD},
        "doc_count": 0,
        "created_at": now(),
    }
    datasets_db.data.insert(0, ds)
    datasets_db.save()
    return ok(ds)


@router.get("/datasets/{ds_id}")
async def get_dataset(ds_id: str):
    ds = find(datasets_db.data, id=ds_id)
    if not ds:
        raise HTTPException(404, detail=err(40400, "知识库不存在"))
    return ok(ds)


@router.patch("/datasets/{ds_id}")
async def update_dataset(ds_id: str, body: dict):
    ds = find(datasets_db.data, id=ds_id)
    if not ds:
        raise HTTPException(404, detail=err(40400, "知识库不存在"))
    for k in ("name", "description", "chunk_config", "retrieval_config"):
        if k in body:
            ds[k] = body[k]
    datasets_db.save()
    return ok(ds)


@router.delete("/datasets/{ds_id}")
async def delete_dataset(ds_id: str):
    datasets_db.data = [d for d in datasets_db.data if d["id"] != ds_id]
    documents_db.data = [d for d in documents_db.data if d["dataset_id"] != ds_id]
    chunks_db.data = {k: v for k, v in chunks_db.data.items()
                      if k not in {d["id"] for d in documents_db.data}}
    VectorStore(ds_id).vec_path.unlink(missing_ok=True)
    VectorStore(ds_id).meta_path.unlink(missing_ok=True)
    for db_ in (datasets_db, documents_db, chunks_db):
        db_.save()
    return ok(None)


# ---------- 文档 ----------

async def _ingest(doc_id: str, file_path, dataset: dict):
    """后台：解析 → 切分 → 嵌入 → 入库。"""
    doc = find(documents_db.data, id=doc_id)
    try:
        text = parse_file(file_path)
        chunks = chunk_text(text, dataset["chunk_config"]["max_length"], dataset["chunk_config"]["overlap"])
        entries = [{"chunk_id": uid("ch"), "doc_id": doc_id, "index": i + 1, "content": c}
                   for i, c in enumerate(chunks)]
        if entries:
            vectors = await embed_texts(EMBED_MODEL, [e["content"] for e in entries])
            VectorStore(dataset["id"]).add(EMBED_MODEL, entries, vectors)
            chunks_db.data[doc_id] = [{**e, "enabled": True} for e in entries]
        doc.update(status="completed", chunk_count=len(entries))
    except Exception as e:
        doc.update(status="failed", error=str(e)[:200])
    chunks_db.save()
    documents_db.save()


@router.post("/datasets/{ds_id}/documents")
async def upload_document(ds_id: str, background: BackgroundTasks, file: UploadFile = File(...)):
    ds = find(datasets_db.data, id=ds_id)
    if not ds:
        raise HTTPException(404, detail=err(40400, "知识库不存在"))
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(422, detail=err(42200, f"文件超过 {config.MAX_UPLOAD_MB}MB 限制"))
    path = save_upload(data, file.filename or "untitled")
    doc = {"id": uid("doc"), "dataset_id": ds_id, "filename": file.filename,
           "size": len(data), "status": "parsing", "chunk_count": 0, "created_at": now()}
    documents_db.data.insert(0, doc)
    ds["doc_count"] += 1
    documents_db.save()
    datasets_db.save()
    background.add_task(_ingest, doc["id"], path, ds)
    return ok([doc])


@router.get("/datasets/{ds_id}/documents")
async def list_documents(ds_id: str):
    return ok([d for d in documents_db.data if d["dataset_id"] == ds_id])


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    doc = find(documents_db.data, id=doc_id)
    if not doc:
        raise HTTPException(404, detail=err(40400, "文档不存在"))
    VectorStore(doc["dataset_id"]).remove_doc(doc_id)
    documents_db.data = [d for d in documents_db.data if d["id"] != doc_id]
    chunks_db.data.pop(doc_id, None)
    ds = find(datasets_db.data, id=doc["dataset_id"])
    if ds:
        ds["doc_count"] = max(0, ds["doc_count"] - 1)
    for db_ in (documents_db, chunks_db, datasets_db):
        db_.save()
    return ok(None)


@router.get("/documents/{doc_id}/chunks")
async def list_chunks(doc_id: str):
    return ok(chunks_db.data.get(doc_id, []))


@router.patch("/chunks/{chunk_id}")
async def update_chunk(chunk_id: str, body: dict):
    for doc_id, chunks in chunks_db.data.items():
        for c in chunks:
            if c["chunk_id"] == chunk_id:
                if "enabled" in body:
                    c["enabled"] = body["enabled"]
                if "content" in body:
                    c["content"] = body["content"]
                chunks_db.save()
                return ok(c)
    raise HTTPException(404, detail=err(40400, "分段不存在"))


@router.post("/datasets/{ds_id}/hit-testing")
async def hit_testing(ds_id: str, body: dict):
    ds = find(datasets_db.data, id=ds_id)
    if not ds:
        raise HTTPException(404, detail=err(40400, "知识库不存在"))
    query = body.get("query", "").strip()
    top_k = body.get("top_k", ds["retrieval_config"]["top_k"])
    threshold = ds["retrieval_config"].get("score_threshold", config.RETRIEVAL_SCORE_THRESHOLD)
    if not query:
        return ok({"items": []})
    try:
        qvec = (await embed_texts(EMBED_MODEL, [query]))[0]
    except Exception as e:
        raise HTTPException(500, detail=err(50001, f"嵌入失败（检查 Ollama 与 bge-m3）：{e}"))
    vs = VectorStore(ds_id)
    hits = vs.search(qvec, top_k, threshold)
    # 过滤禁用分段
    enabled_map: dict[str, bool] = {}
    for chunks in chunks_db.data.values():
        for c in chunks:
            enabled_map[c["chunk_id"]] = c.get("enabled", True)
    hits = [h for h in hits if enabled_map.get(h.chunk_id, True)]
    return ok({"items": [{"chunk": {"id": h.chunk_id, "chunk_id": h.chunk_id, "document_id": h.doc_id,
                                     "index": h.index, "content": h.content, "enabled": True},
                          "score": round(h.score, 4)} for h in hits]})

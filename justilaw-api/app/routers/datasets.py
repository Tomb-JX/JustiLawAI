"""知识库：dataset / document / chunk / hit-testing / reindex（真实 RAG 管线）。

上传 → 后台任务：解析 → 切分 → 嵌入（知识库绑定的嵌入模型）→ 向量入库；状态轮询对齐契约。
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from .. import config
from ..auth import current_user
from ..model_gateway.gateway import embed_texts, provider_store
from ..rag.pipeline import SUPPORTED_SUFFIXES, VectorStore, chunk_text, parse_file
from ..rag.retrieval import dataset_embed_model, retrieve
from ..resp import err, ok
from ..store import chunks_db, datasets_db, documents_db, find, now, save_upload, uid

router = APIRouter(dependencies=[Depends(current_user)])


def _visible_ds(ds: dict, user: dict) -> bool:
    """知识库可见性：自己的 + 系统种子库对所有人可见，其余仅管理员（对齐智能体的可见性规则）。"""
    return (ds.get("created_by") in (None, "u_system", user["id"]) or user["role"] == "admin")


def _get_ds(ds_id: str, user: dict) -> dict:
    ds = find(datasets_db.data, id=ds_id)
    if not ds or not _visible_ds(ds, user):
        raise HTTPException(404, detail=err(40400, "知识库不存在"))
    return ds


def _check_owner(item: dict, user: dict):
    if user["role"] != "admin" and item.get("created_by") not in (None, user["id"]):
        raise HTTPException(403, detail=err(40300, "只能修改自己创建的知识库"))


def _public_chunk(c: dict) -> dict:
    """存储字段 chunk_id/doc_id → 契约字段 id/document_id（两套都返回，兼容旧调用）。"""
    return {"id": c["chunk_id"], "chunk_id": c["chunk_id"], "document_id": c["doc_id"],
            "index": c["index"], "content": c["content"], "enabled": c.get("enabled", True)}


def _sync_doc_count(ds_id: str):
    ds = find(datasets_db.data, id=ds_id)
    if ds:
        ds["doc_count"] = sum(1 for d in documents_db.data if d["dataset_id"] == ds_id)


# ---------- 知识库 ----------

@router.get("/datasets")
async def list_datasets(user: dict = Depends(current_user)):
    for ds in datasets_db.data:
        ds.setdefault("embed_model", dataset_embed_model(ds))
    return ok([ds for ds in datasets_db.data if _visible_ds(ds, user)])


@router.post("/datasets")
async def create_dataset(body: dict, user: dict = Depends(current_user)):
    embed_model = body.get("embed_model") or provider_store.default_model("embedding")
    if body.get("embed_model") and not provider_store.model_info(embed_model):
        raise HTTPException(422, detail=err(42200, f"嵌入模型不存在：{embed_model}"))
    ds = {
        "id": uid("d"),
        "name": (body.get("name") or "未命名知识库").strip(),
        "description": body.get("description"),
        "chunk_config": body.get("chunk_config") or {"max_length": config.CHUNK_MAX_LENGTH, "overlap": config.CHUNK_OVERLAP},
        "retrieval_config": body.get("retrieval_config") or {"top_k": config.RETRIEVAL_TOP_K, "score_threshold": config.RETRIEVAL_SCORE_THRESHOLD},
        "embed_model": embed_model,
        "doc_count": 0,
        "created_by": user["id"],
        "created_at": now(),
    }
    datasets_db.data.insert(0, ds)
    datasets_db.save()
    return ok(ds)


@router.get("/datasets/{ds_id}")
async def get_dataset(ds_id: str, user: dict = Depends(current_user)):
    ds = _get_ds(ds_id, user)
    ds.setdefault("embed_model", dataset_embed_model(ds))
    return ok(ds)


@router.patch("/datasets/{ds_id}")
async def update_dataset(ds_id: str, body: dict, user: dict = Depends(current_user)):
    ds = _get_ds(ds_id, user)
    _check_owner(ds, user)
    if body.get("embed_model") and body["embed_model"] != ds.get("embed_model"):
        if VectorStore(ds_id).size():
            raise HTTPException(422, detail=err(42200, "知识库已有向量，切换嵌入模型请使用「重建索引」"))
        ds["embed_model"] = body["embed_model"]
    for k in ("name", "description", "chunk_config", "retrieval_config"):
        if k in body:
            ds[k] = body[k]
    datasets_db.save()
    return ok(ds)


@router.delete("/datasets/{ds_id}")
async def delete_dataset(ds_id: str, user: dict = Depends(current_user)):
    ds = _get_ds(ds_id, user)
    _check_owner(ds, user)
    removed_docs = {d["id"] for d in documents_db.data if d["dataset_id"] == ds_id}
    datasets_db.data = [d for d in datasets_db.data if d["id"] != ds_id]
    documents_db.data = [d for d in documents_db.data if d["dataset_id"] != ds_id]
    chunks_db.data = {k: v for k, v in chunks_db.data.items() if k not in removed_docs}
    VectorStore(ds_id).clear()
    for db_ in (datasets_db, documents_db, chunks_db):
        db_.save()
    return ok(None)


# ---------- 文档 ----------

async def _ingest(doc_id: str, file_path, ds_id: str):
    """后台：解析 → 切分 → 嵌入 → 入库。"""
    doc = find(documents_db.data, id=doc_id)
    ds = find(datasets_db.data, id=ds_id)
    if not doc or not ds:
        return
    doc["status"] = "parsing"
    documents_db.save()
    try:
        text = parse_file(file_path)
        cc = ds["chunk_config"]
        chunks = chunk_text(text, cc["max_length"], cc["overlap"])
        if not chunks:
            raise ValueError("文件中没有可提取的文本")
        entries = [{"chunk_id": uid("ch"), "doc_id": doc_id, "index": i + 1, "content": c}
                   for i, c in enumerate(chunks)]
        model = dataset_embed_model(ds)
        vectors = await embed_texts(model, [e["content"] for e in entries])
        # 嵌入耗时期间文档可能已被删除
        if not find(documents_db.data, id=doc_id):
            return
        VectorStore(ds_id).add(model, entries, vectors)
        ds["embed_model"] = model
        chunks_db.data[doc_id] = [{**e, "enabled": True} for e in entries]
        doc.update(status="completed", chunk_count=len(entries), error=None)
    except Exception as e:
        doc.update(status="failed", error=str(e)[:300])
    for db_ in (chunks_db, documents_db, datasets_db):
        db_.save()


@router.post("/datasets/{ds_id}/documents")
async def upload_documents(ds_id: str, background: BackgroundTasks,
                           file: list[UploadFile] = File(...), user: dict = Depends(current_user)):
    ds = _get_ds(ds_id, user)
    docs = []
    for f in file:
        name = f.filename or "untitled"
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        data = await f.read()
        if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(422, detail=err(42200, f"{name} 超过 {config.MAX_UPLOAD_MB}MB 限制"))
        doc = {"id": uid("doc"), "dataset_id": ds_id, "filename": name, "size": len(data),
               "status": "queued", "chunk_count": 0, "created_by": user["id"], "created_at": now()}
        if suffix not in SUPPORTED_SUFFIXES:
            # 不支持的格式直接标记失败，用户能在列表里看到原因
            doc.update(status="failed", error=(
                "暂不支持旧版 .doc，请另存为 .docx 后上传" if suffix == ".doc"
                else f"不支持的文件类型 {suffix or '（无扩展名）'}"))
        else:
            path = save_upload(data, name)
            background.add_task(_ingest, doc["id"], path, ds_id)
        documents_db.data.insert(0, doc)
        docs.append(doc)
    _sync_doc_count(ds_id)
    documents_db.save()
    datasets_db.save()
    return ok(docs)


@router.get("/datasets/{ds_id}/documents")
async def list_documents(ds_id: str):
    return ok([d for d in documents_db.data if d["dataset_id"] == ds_id])


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, user: dict = Depends(current_user)):
    doc = find(documents_db.data, id=doc_id)
    if not doc:
        raise HTTPException(404, detail=err(40400, "文档不存在"))
    ds = find(datasets_db.data, id=doc["dataset_id"])
    if ds:
        _check_owner(ds, user)
    VectorStore(doc["dataset_id"]).remove_doc(doc_id)
    documents_db.data = [d for d in documents_db.data if d["id"] != doc_id]
    chunks_db.data.pop(doc_id, None)
    _sync_doc_count(doc["dataset_id"])
    for db_ in (documents_db, chunks_db, datasets_db):
        db_.save()
    return ok(None)


@router.get("/documents/{doc_id}/chunks")
async def list_chunks(doc_id: str):
    return ok([_public_chunk(c) for c in chunks_db.data.get(doc_id, [])])


@router.patch("/chunks/{chunk_id}")
async def update_chunk(chunk_id: str, body: dict):
    for doc_id, chunks in chunks_db.data.items():
        for c in chunks:
            if c["chunk_id"] != chunk_id:
                continue
            doc = find(documents_db.data, id=doc_id)
            vs = VectorStore(doc["dataset_id"])
            vector = None
            content = body.get("content")
            if content is not None and content.strip() and content != c["content"]:
                ds = find(datasets_db.data, id=doc["dataset_id"])
                try:
                    vector = (await embed_texts(dataset_embed_model(ds), [content]))[0]
                except Exception as e:
                    raise HTTPException(500, detail=err(50001, f"重新嵌入失败：{e}"))
                c["content"] = content
            if "enabled" in body:
                c["enabled"] = bool(body["enabled"])
            vs.update_chunk(chunk_id, enabled=c.get("enabled", True),
                            content=c["content"] if vector is not None else None, vector=vector)
            chunks_db.save()
            return ok(_public_chunk(c))
    raise HTTPException(404, detail=err(40400, "分段不存在"))


@router.post("/datasets/{ds_id}/reindex")
async def reindex_dataset(ds_id: str, body: dict | None = None, user: dict = Depends(current_user)):
    """用（新的）嵌入模型重建整个知识库的向量；分段内容与启停状态保留。"""
    ds = _get_ds(ds_id, user)
    _check_owner(ds, user)
    model = (body or {}).get("embed_model") or dataset_embed_model(ds)
    if not provider_store.model_info(model):
        raise HTTPException(422, detail=err(42200, f"嵌入模型不存在：{model}"))
    doc_ids = [d["id"] for d in documents_db.data if d["dataset_id"] == ds_id and d["status"] == "completed"]
    entries = [c for did in doc_ids for c in chunks_db.data.get(did, [])]
    vectors = []
    if entries:
        try:
            vectors = await embed_texts(model, [c["content"] for c in entries])
        except Exception as e:
            raise HTTPException(500, detail=err(50001, f"重建索引失败：{e}"))
    vs = VectorStore(ds_id)
    vs.clear()
    if entries:
        vs.add(model, entries, vectors)
    ds["embed_model"] = model
    datasets_db.save()
    return ok({"chunk_count": len(entries), "embed_model": model})


@router.post("/datasets/{ds_id}/hit-testing")
async def hit_testing(ds_id: str, body: dict, user: dict = Depends(current_user)):
    ds = _get_ds(ds_id, user)
    query = (body.get("query") or "").strip()
    if not query:
        return ok({"items": []})
    try:
        hits = await retrieve([ds_id], query, body.get("top_k") or ds["retrieval_config"]["top_k"])
    except Exception as e:
        raise HTTPException(500, detail=err(50001, f"检索失败（检查嵌入模型是否可用）：{e}"))
    return ok({"items": [{
        "chunk": {"id": h.chunk_id, "chunk_id": h.chunk_id, "document_id": h.doc_id,
                  "index": h.index, "content": h.content, "enabled": True},
        "score": round(h.score, 4),
    } for h in hits]})

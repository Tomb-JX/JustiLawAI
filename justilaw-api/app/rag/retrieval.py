"""跨知识库检索：对话 / 命中测试 / 工作流共用。

每个知识库用建库时的嵌入模型向量化查询，并使用自己的 top_k 与相似度阈值。
"""
from __future__ import annotations

from ..model_gateway.gateway import embed_texts, provider_store
from ..store import datasets_db, documents_db, find
from .pipeline import Hit, VectorStore


def dataset_embed_model(ds: dict) -> str | None:
    return ds.get("embed_model") or provider_store.default_model("embedding")


async def retrieve(dataset_ids: list[str], query: str, top_k: int | None = None) -> list[Hit]:
    query = query.strip()
    if not query or not dataset_ids:
        return []
    qvec_cache: dict[str, list[float]] = {}
    hits: list[Hit] = []
    cap = top_k or 0
    for ds_id in dict.fromkeys(dataset_ids):  # 去重保序
        ds = find(datasets_db.data, id=ds_id)
        if not ds:
            continue
        vs = VectorStore(ds_id)
        if vs.size() == 0:
            continue
        model = dataset_embed_model(ds)
        if model not in qvec_cache:
            qvec_cache[model] = (await embed_texts(model, [query]))[0]
        rc = ds.get("retrieval_config") or {}
        k = top_k or rc.get("top_k", 5)
        cap = max(cap, k)
        hits.extend(vs.search(qvec_cache[model], k, rc.get("score_threshold", 0.35)))
    hits.sort(key=lambda h: h.score, reverse=True)
    # 多库合并后仍只保留 top_k 条，避免上下文随挂载库数量膨胀
    return hits[:cap]


def to_citations(hits: list[Hit]) -> list[dict]:
    names = {d["id"]: d["filename"] for d in documents_db.data}
    return [{
        "index": i + 1,
        "source": f"{names.get(h.doc_id, h.doc_id)} · 分段{h.index}",
        "snippet": h.content[:200],
        "score": round(h.score, 4),
        "doc_id": h.doc_id,
        "chunk_id": h.chunk_id,
    } for i, h in enumerate(hits)]


def to_context(hits: list[Hit]) -> str:
    return "\n\n".join(f"[{i + 1}] {h.content}" for i, h in enumerate(hits))

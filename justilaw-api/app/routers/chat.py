"""对话补全（核心）：POST /chat/completions → SSE 事件流（对齐前端契约）。

链路：
  请求(agent_id?) → 取智能体 system_prompt 注入 → RAG 检索(可选) →
  模型网关流式生成 → message/reasoning/citations/done 事件推送 → 消息落库
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import config
from ..model_gateway.gateway import embed_texts, stream_chat, provider_store
from ..rag.pipeline import VectorStore
from ..store import conversations_db, messages_db, agents_db, find, now, record_call, uid

router = APIRouter()

EMBED_MODEL = f"ollama/{config.DEFAULT_EMBED_MODEL}"

DEFAULT_SYSTEM = (
    "你是 JustiLawAI 法律智能助手。回答力求准确、结构化（适当使用标题/列表/表格），"
    "引用法条时注明条文出处，语言通俗。结尾声明：以上内容由 AI 生成，仅供参考，不构成法律意见。"
)

RAG_PROMPT_TMPL = (
    "请优先依据以下检索到的资料回答用户问题，并在引用处标注 [编号]；"
    "若资料不足以回答，请明确说明并基于一般法律知识谨慎作答。\n\n"
    "【检索资料】\n{context}\n\n【用户问题】\n{question}"
)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/completions")
async def chat_completions(req: Request):
    body = await req.json()
    cid: str = body["conversation_id"]
    model: str = body.get("model") or config.DEFAULT_CHAT_MODEL
    if "/" not in model:
        model = f"ollama/{model}"
    params: dict = body.get("params") or {}
    thinking: bool = bool(body.get("thinking"))
    retrieval: dict | None = body.get("retrieval")
    history: list[dict] = body["messages"]

    # 1) 智能体上下文（system_prompt 服务端注入，前端不可篡改）
    system_prompt = DEFAULT_SYSTEM
    agent = None
    if body.get("agent_id"):
        agent = find(agents_db.data, id=body["agent_id"])
        if agent and agent.get("system_prompt"):
            system_prompt = agent["system_prompt"]

    # 2) 重建历史（以请求上下文为准，天然支持"重新生成/编辑重发"）
    msgs = [{"id": uid("m"), "conversation_id": cid, "role": m["role"],
             "content_type": "markdown", "content": m["content"], "status": "done",
             "created_at": now()} for m in history]
    messages_db.data[cid] = msgs

    question = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

    # 3) RAG 检索（挂载智能体知识库 或 请求显式开启）
    dataset_ids: list[str] = []
    if agent and agent.get("dataset_ids"):
        dataset_ids = agent["dataset_ids"]
    if retrieval and retrieval.get("dataset_ids"):
        dataset_ids = retrieval["dataset_ids"]
    top_k = (retrieval or {}).get("top_k", config.RETRIEVAL_TOP_K)

    citations = None
    user_content = question
    if dataset_ids:
        try:
            qvec = (await embed_texts(EMBED_MODEL, [question]))[0]
            hits = []
            for ds_id in dataset_ids:
                ds = find(datasets_db.data, id=ds_id)
                if not ds:
                    continue
                vs = VectorStore(ds_id)
                hits.extend(vs.search(qvec, top_k, config.RETRIEVAL_SCORE_THRESHOLD))
            hits.sort(key=lambda h: h.score, reverse=True)
            hits = hits[:top_k]
            if hits:
                citations = [{
                    "index": i + 1,
                    "source": next(
                        (d["filename"] for d in documents_db.data if d["id"] == h.doc_id), h.doc_id
                    ) + f" · 分段{h.index}",
                    "snippet": h.content[:200],
                    "score": round(h.score, 4),
                    "doc_id": h.doc_id,
                    "chunk_id": h.chunk_id,
                } for i, h in enumerate(hits)]
                context = "\n\n".join(f"[{i+1}] {h.content}" for i, h in enumerate(hits))
                user_content = RAG_PROMPT_TMPL.format(context=context, question=question)
        except Exception as e:  # 检索失败不阻塞生成
            print(f"[rag] 检索失败: {e}")

    llm_messages = [{"role": "system", "content": system_prompt}]
    llm_messages += [{"role": m["role"], "content": m["content"]} for m in history[:-1]]
    llm_messages.append({"role": "user", "content": user_content})

    record_call(model)

    async def gen():
        assistant_id = uid("m")
        full_text, full_thinking = "", ""
        try:
            if citations:
                yield sse("citations", {"items": citations})
            async for delta in stream_chat(model, llm_messages, params, thinking):
                if delta.thinking:
                    full_thinking += delta.thinking
                    yield sse("reasoning", {"delta": delta.thinking})
                if delta.text:
                    full_text += delta.text
                    yield sse("message", {"delta": delta.text})
        except Exception as e:
            yield sse("error", {"code": 50001, "message": f"模型生成失败：{e}"})
            # 已生成部分仍落库
        usage = {
            "prompt_tokens": max(1, len(question) // 2),
            "completion_tokens": max(1, len(full_text) // 2),
        }
        messages_db.data[cid].append({
            "id": assistant_id, "conversation_id": cid, "role": "assistant",
            "content_type": "markdown", "content": full_text or "（无输出）",
            "citations": citations, "reasoning": full_thinking or None,
            "status": "done", "usage": usage, "created_at": now(),
        })
        messages_db.save()
        conv = find(conversations_db.data, id=cid)
        if conv:
            conv["last_message_at"] = now()
            if conv.get("title") in ("新对话", None) and question:
                conv["title"] = question[:24]
            conversations_db.save()
        yield sse("done", {"message_id": assistant_id, "usage": usage})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

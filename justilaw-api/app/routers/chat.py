"""对话补全（核心）：POST /chat/completions → SSE 事件流（对齐前端契约）。

链路：
  请求(agent_id?) → 取智能体 system_prompt 注入 → 附件文本注入 → RAG 检索(可选) →
  模型网关流式生成 → message/reasoning/citations/done 事件推送 → 消息落库
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import config
from ..auth import current_user
from ..model_gateway.gateway import provider_store, stream_chat
from ..rag.retrieval import retrieve, to_citations, to_context
from ..resp import err
from ..store import (agents_db, conversations_db, find, messages_db, now, record_call, uid,
                     users_db)
from .files import attachment_text

router = APIRouter()
log = logging.getLogger("justilaw.chat")

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


def _estimate_tokens(text: str) -> int:
    # 上游未返回用量时的粗估：中文约 1 字 ≈ 1 token
    return max(1, len(text))


@router.post("/chat/completions")
async def chat_completions(body: dict, user: dict = Depends(current_user)):
    cid: str = body["conversation_id"]
    history: list[dict] = body.get("messages") or []
    if not history or history[-1].get("role") != "user":
        raise HTTPException(422, detail=err(42200, "messages 最后一条必须是用户消息"))

    conv = find(conversations_db.data, id=cid)
    if conv and conv.get("owner_id") not in (None, user["id"]) and user["role"] != "admin":
        raise HTTPException(403, detail=err(40300, "无权访问该会话"))
    if not conv:  # 前端未先建会话时兜底创建
        conv = {"id": cid, "title": "新对话", "agent_id": body.get("agent_id"), "pinned": False,
                "owner_id": user["id"], "last_message_at": now(), "created_at": now()}
        conversations_db.data.insert(0, conv)

    model: str = body.get("model") or provider_store.default_model("chat") or ""
    if model and "/" not in model:
        model = f"ollama/{model}"
    if not model:
        raise HTTPException(422, detail=err(42200, "没有可用的对话模型，请先在「模型服务」页配置"))
    params: dict = body.get("params") or {}
    thinking: bool = bool(body.get("thinking"))
    retrieval: dict | None = body.get("retrieval")

    # 1) 智能体上下文（system_prompt 服务端注入，前端不可篡改）
    system_prompt = DEFAULT_SYSTEM
    agent = find(agents_db.data, id=body["agent_id"]) if body.get("agent_id") else None
    if agent and agent.get("system_prompt"):
        system_prompt = agent["system_prompt"]

    question = history[-1]["content"]
    attachments = body.get("attachments") or []

    # 2) 重建历史（以请求上下文为准，天然支持"重新生成/编辑重发"）
    msgs = [{"id": uid("m"), "conversation_id": cid, "role": m["role"],
             "content_type": "markdown", "content": m["content"], "status": "done",
             "created_at": now()} for m in history]
    if attachments:
        msgs[-1]["attachments"] = [{"file_id": a["file_id"], "filename": a.get("filename", ""),
                                    "size": a.get("size", 0)} for a in attachments]
    messages_db.data[cid] = msgs

    # 3) 附件文本注入
    user_content = question
    attach_blocks = []
    for a in attachments:
        text = attachment_text(a["file_id"], user)
        if text:
            attach_blocks.append(f"【附件：{a.get('filename') or a['file_id']}】\n{text[:config.ATTACHMENT_MAX_CHARS]}")
    if attach_blocks:
        user_content = "\n\n".join(attach_blocks) + f"\n\n【用户问题】\n{question}"

    # 4) RAG 检索（请求显式指定优先，否则用智能体挂载的知识库）
    dataset_ids: list[str] = list((retrieval or {}).get("dataset_ids") or (agent or {}).get("dataset_ids") or [])
    citations = None
    rag_error = None
    if dataset_ids:
        try:
            hits = await retrieve(dataset_ids, question, (retrieval or {}).get("top_k"))
            if hits:
                citations = to_citations(hits)
                user_content = RAG_PROMPT_TMPL.format(context=to_context(hits), question=user_content)
        except Exception as e:  # 检索失败不阻塞生成，但要让用户知道
            log.warning("检索失败：%s", e)
            rag_error = f"知识库检索失败，本次回答未使用知识库：{e}"

    llm_messages = [{"role": "system", "content": system_prompt}]
    llm_messages += [{"role": m["role"], "content": m["content"]} for m in history[:-1]]
    llm_messages.append({"role": "user", "content": user_content})

    async def gen():
        assistant_id = uid("m")
        full_text, full_thinking = "", ""
        usage = None
        status = "done"
        error_event = None
        try:
            if rag_error:
                yield sse("tool_call", {"name": "knowledge_retrieval", "status": "failed", "message": rag_error})
            if citations:
                yield sse("citations", {"items": citations})
            async for delta in stream_chat(model, llm_messages, params, thinking):
                if delta.usage is not None:
                    usage = delta.usage
                if delta.thinking:
                    full_thinking += delta.thinking
                    yield sse("reasoning", {"delta": delta.thinking})
                if delta.text:
                    full_text += delta.text
                    yield sse("message", {"delta": delta.text})
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断开 = 停止生成（契约 §3.3）：已生成部分在 finally 中落库为 aborted；
            # 断开后不能再 yield，必须把取消继续抛出
            status = "aborted"
            raise
        except Exception as e:
            status = "error"
            error_event = sse("error", {"code": 50001, "message": f"模型生成失败：{e}"})
        finally:
            if not usage or not usage.get("completion_tokens"):
                usage = {"prompt_tokens": _estimate_tokens("".join(m["content"] for m in llm_messages)),
                         "completion_tokens": _estimate_tokens(full_text)}
            _persist(cid, conv, question, agent, user, model, usage, {
                "id": assistant_id, "conversation_id": cid, "role": "assistant",
                "content_type": "markdown", "content": full_text or ("（已停止）" if status == "aborted" else "（无输出）"),
                "citations": citations, "reasoning": full_thinking or None,
                "status": status, "usage": usage, "created_at": now(),
            })
        if error_event:
            yield error_event
        yield sse("done", {"message_id": assistant_id, "usage": usage})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _persist(cid: str, conv: dict, question: str, agent: dict | None, user: dict,
             model: str, usage: dict, assistant_msg: dict):
    messages_db.data.setdefault(cid, []).append(assistant_msg)
    messages_db.save()
    conv["last_message_at"] = now()
    if conv.get("title") in ("新对话", None) and question:
        conv["title"] = question[:24]
    conversations_db.save()
    record_call(model, usage)
    u = find(users_db.data, id=user["id"])
    if u:
        u["call_count"] = u.get("call_count", 0) + 1
        users_db.save()
    if agent:
        agent["usage_count"] = agent.get("usage_count", 0) + 1
        agents_db.save()

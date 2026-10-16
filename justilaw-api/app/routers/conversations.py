"""会话与消息管理（按用户隔离）。"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import current_user
from ..resp import err, ok
from ..store import conversations_db, find, messages_db, now, uid

router = APIRouter()


def _owned(cid: str, user: dict) -> dict:
    conv = find(conversations_db.data, id=cid)
    # 旧数据没有 owner_id，视为本地用户所有（单用户模式下即当前用户）
    if not conv or conv.get("owner_id", user["id"]) != user["id"]:
        raise HTTPException(404, detail=err(40400, "会话不存在"))
    return conv


@router.get("/conversations")
async def list_conversations(agent_id: str | None = None, user: dict = Depends(current_user)):
    items = [c for c in conversations_db.data
             if c.get("owner_id", user["id"]) == user["id"] and (not agent_id or c.get("agent_id") == agent_id)]
    items.sort(key=lambda c: c.get("last_message_at", ""), reverse=True)
    items.sort(key=lambda c: bool(c.get("pinned")), reverse=True)
    return ok(items)


@router.post("/conversations")
async def create_conversation(body: dict | None = None, user: dict = Depends(current_user)):
    body = body or {}
    conv = {
        "id": uid("c"), "title": (body.get("title") or "新对话")[:30],
        "agent_id": body.get("agent_id"), "pinned": False, "owner_id": user["id"],
        "last_message_at": now(), "created_at": now(),
    }
    conversations_db.data.insert(0, conv)
    messages_db.data[conv["id"]] = []
    conversations_db.save()
    messages_db.save()
    return ok(conv)


@router.patch("/conversations/{cid}")
async def update_conversation(cid: str, body: dict, user: dict = Depends(current_user)):
    conv = _owned(cid, user)
    for k in ("title", "pinned"):
        if k in body:
            conv[k] = body[k]
    conversations_db.save()
    return ok(conv)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, user: dict = Depends(current_user)):
    _owned(cid, user)
    conversations_db.data = [c for c in conversations_db.data if c["id"] != cid]
    messages_db.data.pop(cid, None)
    conversations_db.save()
    messages_db.save()
    return ok(None)


@router.get("/conversations/{cid}/messages")
async def list_messages(cid: str, user: dict = Depends(current_user)):
    _owned(cid, user)
    return ok({"list": messages_db.data.get(cid, []), "next_cursor": None})


@router.delete("/conversations/{cid}/messages")
async def clear_messages(cid: str, user: dict = Depends(current_user)):
    _owned(cid, user)
    messages_db.data[cid] = []
    messages_db.save()
    return ok(None)


@router.delete("/conversations/{cid}/messages/{mid}")
async def delete_message(cid: str, mid: str, user: dict = Depends(current_user)):
    """删除单条消息（重新生成前清理旧回复、用户撤回自己的提问等场景）。"""
    _owned(cid, user)
    msgs = messages_db.data.get(cid, [])
    if not any(m["id"] == mid for m in msgs):
        raise HTTPException(404, detail=err(40400, "消息不存在"))
    messages_db.data[cid] = [m for m in msgs if m["id"] != mid]
    messages_db.save()
    return ok(None)


@router.post("/conversations/{cid}/messages/{mid}/feedback")
async def message_feedback(cid: str, mid: str, body: dict, user: dict = Depends(current_user)):
    """消息点赞/点踩：rating ∈ up | down；传 null 取消（FR-C5 反馈数据落库）。"""
    _owned(cid, user)
    m = find(messages_db.data.get(cid, []), id=mid)
    if not m:
        raise HTTPException(404, detail=err(40400, "消息不存在"))
    rating = body.get("rating")
    if rating not in ("up", "down", None):
        raise HTTPException(422, detail=err(42200, "rating 只能是 up / down / null"))
    if rating:
        m["feedback"] = rating
    else:
        m.pop("feedback", None)
    messages_db.save()
    return ok({"id": mid, "feedback": rating})

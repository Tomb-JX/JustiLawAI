"""会话与消息管理。"""
from fastapi import APIRouter, HTTPException

from ..resp import err, ok
from ..store import conversations_db, messages_db, find, now, uid

router = APIRouter()


@router.get("/conversations")
async def list_conversations():
    items = sorted(conversations_db.data, key=lambda c: (not c.get("pinned"), c.get("last_message_at", "")), reverse=False)
    items.sort(key=lambda c: c.get("last_message_at", ""), reverse=True)
    items.sort(key=lambda c: bool(c.get("pinned")), reverse=True)
    return ok(items)


@router.post("/conversations")
async def create_conversation(body: dict = {}):
    conv = {
        "id": uid("c"), "title": (body.get("title") or "新对话")[:30],
        "agent_id": body.get("agent_id"), "pinned": False,
        "last_message_at": now(), "created_at": now(),
    }
    conversations_db.data.insert(0, conv)
    messages_db.data[conv["id"]] = []
    conversations_db.save()
    messages_db.save()
    return ok(conv)


@router.patch("/conversations/{cid}")
async def update_conversation(cid: str, body: dict):
    conv = find(conversations_db.data, id=cid)
    if not conv:
        raise HTTPException(404, detail=err(40400, "会话不存在"))
    for k in ("title", "pinned"):
        if k in body:
            conv[k] = body[k]
    conversations_db.save()
    return ok(conv)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str):
    conversations_db.data = [c for c in conversations_db.data if c["id"] != cid]
    messages_db.data.pop(cid, None)
    conversations_db.save()
    messages_db.save()
    return ok(None)


@router.get("/conversations/{cid}/messages")
async def list_messages(cid: str):
    return ok({"list": messages_db.data.get(cid, []), "next_cursor": None})


@router.delete("/conversations/{cid}/messages")
async def clear_messages(cid: str):
    messages_db.data[cid] = []
    messages_db.save()
    return ok(None)

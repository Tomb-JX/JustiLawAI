"""工作流：CRUD + 试运行（SSE 逐节点事件，对齐契约 §3.5）。"""
from __future__ import annotations

import copy
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..auth import current_user
from ..resp import err, ok
from ..store import find, now, uid, workflows_db
from ..workflow.engine import NodeEvent, run_workflow

router = APIRouter()

BLANK_DSL = {
    "nodes": [
        {"id": "nd_1", "type": "workflow", "position": {"x": 0, "y": 200},
         "data": {"nodeType": "start", "name": "开始", "config": {"vars": [{"name": "query", "label": "输入"}]}}},
        {"id": "nd_2", "type": "workflow", "position": {"x": 240, "y": 200},
         "data": {"nodeType": "reply", "name": "直接回复", "config": {}}},
    ],
    "edges": [{"id": "e_1", "source": "nd_1", "target": "nd_2"}],
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _visible(wf: dict, user: dict) -> bool:
    return (wf.get("created_by") in (None, "u_system", user["id"]) or user["role"] == "admin"
            or wf.get("status") == "published")


def _get(wid: str, user: dict, write: bool = False) -> dict:
    wf = find(workflows_db.data, id=wid)
    if not wf or not _visible(wf, user):
        raise HTTPException(404, detail=err(40400, "工作流不存在"))
    if write and wf.get("created_by") not in (None, user["id"]) and user["role"] != "admin":
        raise HTTPException(403, detail=err(40300, "只能修改自己创建的工作流"))
    return wf


@router.get("/workflows")
async def list_workflows(user: dict = Depends(current_user)):
    return ok([w for w in workflows_db.data if _visible(w, user)])


@router.post("/workflows")
async def create_workflow(body: dict, user: dict = Depends(current_user)):
    if not (body.get("name") or "").strip():
        raise HTTPException(422, detail=err(42200, "name 必填"))
    src = _get(body["from_workflow_id"], user) if body.get("from_workflow_id") else None
    wf = {"id": uid("w"), "name": body["name"].strip(),
          "description": body.get("description") or (src["description"] if src else ""),
          "status": "draft", "created_by": user["id"], "created_at": now(),
          "dsl": copy.deepcopy(src["dsl"] if src else BLANK_DSL)}
    workflows_db.data.insert(0, wf)
    workflows_db.save()
    return ok(wf)


@router.get("/workflows/{wid}")
async def get_workflow(wid: str, user: dict = Depends(current_user)):
    return ok(_get(wid, user))


@router.patch("/workflows/{wid}")
async def update_workflow(wid: str, body: dict, user: dict = Depends(current_user)):
    wf = _get(wid, user, write=True)
    for k in ("name", "description", "dsl", "status"):
        if k in body:
            wf[k] = body[k]
    workflows_db.save()
    return ok(wf)


@router.delete("/workflows/{wid}")
async def delete_workflow(wid: str, user: dict = Depends(current_user)):
    _get(wid, user, write=True)
    workflows_db.data = [w for w in workflows_db.data if w["id"] != wid]
    workflows_db.save()
    return ok(None)


@router.post("/workflows/{wid}/run")
async def run(wid: str, body: dict | None = None, user: dict = Depends(current_user)):
    """body: {inputs: {var: value}, dsl?: 未保存的画布（试运行用当前编辑内容）}"""
    body = body or {}
    wf = _get(wid, user)
    dsl = body.get("dsl") or wf["dsl"]
    inputs = body.get("inputs") or {}

    async def gen():
        try:
            async for ev in run_workflow(dsl, inputs):
                if isinstance(ev, NodeEvent):
                    yield _sse("workflow", {k: v for k, v in ev.__dict__.items() if v is not None})
                else:
                    if ev["answer"]:
                        yield _sse("message", {"delta": ev["answer"]})
                    # 完整结果已在 message 中下发，这里只带各节点输出摘要，避免事件过大
                    yield _sse("done", {"outputs": {k: v[:2000] for k, v in ev["outputs"].items()}})
        except Exception as e:
            yield _sse("error", {"code": 50001, "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

"""智能体 / 提示词 / 文件 / 工作流 / 管理后台 路由。"""
from __future__ import annotations

import httpx

from fastapi import APIRouter, HTTPException, UploadFile, File

from .. import config
from ..model_gateway.gateway import stream_chat
from ..resp import err, ok
from ..store import (agents_db, prompts_db, workflows_db, stats_db, find, now, save_upload, uid)

router = APIRouter()


# ---------- 智能体 ----------

@router.get("/agents")
async def list_agents(scope: str = "all"):
    if scope == "market":
        return ok([a for a in agents_db.data if a["status"] == "published" and a["scope"] == "public"])
    if scope == "mine":
        return ok([a for a in agents_db.data if a["created_by"] == "u_me"])
    return ok(agents_db.data)


@router.post("/agents")
async def create_agent(body: dict):
    agent = {
        "id": uid("a"), "name": body.get("name", "未命名智能体"),
        "category": body.get("category", "法律咨询"), "description": body.get("description", ""),
        "system_prompt": body.get("system_prompt", "你是法律智能助手。"),
        "opening_statement": body.get("opening_statement"),
        "suggested_questions": body.get("suggested_questions", []),
        "tool_ids": body.get("tool_ids", []), "dataset_ids": body.get("dataset_ids", []),
        "scope": body.get("scope", "private"), "status": "draft",
        "usage_count": 0, "created_by": "u_me", "created_at": now(),
    }
    agents_db.data.insert(0, agent)
    agents_db.save()
    return ok(agent)


@router.get("/agents/{aid}")
async def get_agent(aid: str):
    a = find(agents_db.data, id=aid)
    if not a:
        raise HTTPException(404, detail=err(40400, "智能体不存在"))
    return ok(a)


@router.patch("/agents/{aid}")
async def update_agent(aid: str, body: dict):
    a = find(agents_db.data, id=aid)
    if not a:
        raise HTTPException(404, detail=err(40400, "智能体不存在"))
    for k in ("name", "category", "description", "system_prompt", "opening_statement",
              "suggested_questions", "dataset_ids", "scope", "status"):
        if k in body:
            a[k] = body[k]
    agents_db.save()
    return ok(a)


@router.delete("/agents/{aid}")
async def delete_agent(aid: str):
    agents_db.data = [a for a in agents_db.data if a["id"] != aid]
    agents_db.save()
    return ok(None)


# ---------- 提示词 ----------

@router.get("/prompts")
async def list_prompts():
    return ok(prompts_db.data)


@router.post("/prompts")
async def create_prompt(body: dict):
    p = {"id": uid("p"), "name": body["name"], "content": body["content"],
         "category": body.get("category", "常用"), "starred": False}
    prompts_db.data.insert(0, p)
    prompts_db.save()
    return ok(p)


@router.delete("/prompts/{pid}")
async def delete_prompt(pid: str):
    prompts_db.data = [p for p in prompts_db.data if p["id"] != pid]
    prompts_db.save()
    return ok(None)


# ---------- 文件 ----------

@router.post("/files")
async def upload_file(file: UploadFile = File(...)):
    data = await file.read()
    save_upload(data, file.filename or "untitled")
    return ok({"file_id": uid("f"), "filename": file.filename, "size": len(data)})


# ---------- 工作流 ----------

@router.get("/workflows")
async def list_workflows():
    return ok(workflows_db.data)


@router.post("/workflows")
async def create_workflow(body: dict):
    src = find(workflows_db.data, id=body.get("from_workflow_id")) if body.get("from_workflow_id") else None
    import json as _json
    wf = {"id": uid("w"), "name": body["name"], "description": body.get("description", src["description"] if src else ""),
          "status": "draft", "created_at": now(),
          "dsl": _json.loads(_json.dumps(src["dsl"])) if src else {
              "nodes": [
                  {"id": "nd_1", "type": "workflow", "position": {"x": 0, "y": 200},
                   "data": {"nodeType": "start", "name": "开始", "config": {"vars": [{"name": "query", "label": "输入"}]}}},
                  {"id": "nd_2", "type": "workflow", "position": {"x": 240, "y": 200},
                   "data": {"nodeType": "reply", "name": "直接回复", "config": {}}},
              ],
              "edges": [{"id": "e_1", "source": "nd_1", "target": "nd_2"}]}}
    workflows_db.data.insert(0, wf)
    workflows_db.save()
    return ok(wf)


@router.get("/workflows/{wid}")
async def get_workflow(wid: str):
    wf = find(workflows_db.data, id=wid)
    if not wf:
        raise HTTPException(404, detail=err(40400, "工作流不存在"))
    return ok(wf)


@router.patch("/workflows/{wid}")
async def update_workflow(wid: str, body: dict):
    wf = find(workflows_db.data, id=wid)
    if not wf:
        raise HTTPException(404, detail=err(40400, "工作流不存在"))
    for k in ("name", "description", "dsl"):
        if k in body:
            wf[k] = body[k]
    workflows_db.save()
    return ok(wf)


@router.delete("/workflows/{wid}")
async def delete_workflow(wid: str):
    workflows_db.data = [w for w in workflows_db.data if w["id"] != wid]
    workflows_db.save()
    return ok(None)


# ---------- 管理后台统计 ----------

@router.get("/admin/stats/usage")
async def usage_stats():
    daily = [{"date": d, "calls": c} for d, c in sorted(stats_db.data["daily_calls"].items())]
    return ok(daily[-14:])


@router.get("/admin/stats/models")
async def model_stats():
    return ok([{"name": k.split("/")[-1], "value": v}
               for k, v in sorted(stats_db.data["model_calls"].items(), key=lambda x: -x[1])])

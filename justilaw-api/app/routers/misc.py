"""智能体 / 提示词 / 当前用户 / 管理后台 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import AUTH_ENABLED, current_user, public_user, require_admin
from ..resp import err, ok
from ..store import agents_db, find, now, prompts_db, stats_db, uid, users_db

router = APIRouter()

AGENT_FIELDS = ("name", "avatar", "category", "description", "system_prompt", "opening_statement",
                "suggested_questions", "tool_ids", "dataset_ids", "scope", "status")


def _agent_visible(a: dict, user: dict) -> bool:
    return (a.get("created_by") == user["id"] or a.get("created_by") == "u_system"
            or (a.get("status") == "published" and a.get("scope") in ("public", "org"))
            or user["role"] == "admin")


def _owned_agent(aid: str, user: dict) -> dict:
    a = find(agents_db.data, id=aid)
    if not a or not _agent_visible(a, user):
        raise HTTPException(404, detail=err(40400, "智能体不存在"))
    if a.get("created_by") != user["id"] and user["role"] != "admin":
        raise HTTPException(403, detail=err(40300, "只能修改自己创建的智能体"))
    return a


# ---------- 当前用户 ----------

@router.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return ok({**public_user(user), "auth_enabled": AUTH_ENABLED})


@router.put("/users/me")
async def update_me(body: dict, user: dict = Depends(current_user)):
    """前端登录后用 ID Token 中的昵称/邮箱/头像同步资料（access token 里没有这些字段）。"""
    for k in ("nickname", "username", "email", "avatar"):
        if body.get(k):
            user[k] = str(body[k])[:100]
    users_db.save()
    return ok(public_user(user))


# ---------- 智能体 ----------

@router.get("/agents")
async def list_agents(scope: str = "all", user: dict = Depends(current_user)):
    items = [a for a in agents_db.data if _agent_visible(a, user)]
    if scope == "market":
        items = [a for a in items if a["status"] == "published" and a["scope"] in ("public", "org")]
    elif scope == "mine":
        items = [a for a in items if a.get("created_by") == user["id"]]
    return ok(items)


@router.post("/agents")
async def create_agent(body: dict, user: dict = Depends(current_user)):
    agent = {
        "id": uid("a"), "name": body.get("name") or "未命名智能体",
        "avatar": body.get("avatar"),
        "category": body.get("category", "法律咨询"), "description": body.get("description", ""),
        "system_prompt": body.get("system_prompt") or "你是法律智能助手。",
        "opening_statement": body.get("opening_statement"),
        "suggested_questions": body.get("suggested_questions", []),
        "tool_ids": body.get("tool_ids", []), "dataset_ids": body.get("dataset_ids", []),
        "scope": body.get("scope", "private"),
        "status": body.get("status") if body.get("status") in ("draft", "published") else "draft",
        "usage_count": 0, "created_by": user["id"], "created_at": now(),
    }
    agents_db.data.insert(0, agent)
    agents_db.save()
    return ok(agent)


@router.get("/agents/{aid}")
async def get_agent(aid: str, user: dict = Depends(current_user)):
    a = find(agents_db.data, id=aid)
    if not a or not _agent_visible(a, user):
        raise HTTPException(404, detail=err(40400, "智能体不存在"))
    return ok(a)


@router.patch("/agents/{aid}")
async def update_agent(aid: str, body: dict, user: dict = Depends(current_user)):
    a = _owned_agent(aid, user)
    for k in AGENT_FIELDS:
        if k in body:
            a[k] = body[k]
    agents_db.save()
    return ok(a)


@router.post("/agents/{aid}/publish")
async def publish_agent(aid: str, user: dict = Depends(current_user)):
    a = _owned_agent(aid, user)
    a["status"] = "published"
    agents_db.save()
    return ok(a)


@router.post("/agents/{aid}/offline")
async def offline_agent(aid: str, user: dict = Depends(current_user)):
    a = _owned_agent(aid, user)
    a["status"] = "offline"
    agents_db.save()
    return ok(a)


@router.delete("/agents/{aid}")
async def delete_agent(aid: str, user: dict = Depends(current_user)):
    _owned_agent(aid, user)
    agents_db.data = [a for a in agents_db.data if a["id"] != aid]
    agents_db.save()
    return ok(None)


# ---------- 提示词（平台共享） ----------

def _owned_prompt(pid: str, user: dict) -> dict:
    """改/删提示词需要创建者或管理员；种子提示词（无 created_by）仅管理员可动。"""
    p = find(prompts_db.data, id=pid)
    if not p:
        raise HTTPException(404, detail=err(40400, "提示词不存在"))
    if p.get("created_by") != user["id"] and user["role"] != "admin":
        raise HTTPException(403, detail=err(40300, "只能修改自己创建的提示词"))
    return p


@router.get("/prompts", dependencies=[Depends(current_user)])
async def list_prompts():
    return ok(prompts_db.data)


@router.post("/prompts")
async def create_prompt(body: dict, user: dict = Depends(current_user)):
    if not body.get("name") or not body.get("content"):
        raise HTTPException(422, detail=err(42200, "name 与 content 必填"))
    p = {"id": uid("p"), "name": body["name"], "content": body["content"],
         "category": body.get("category", "常用"), "starred": False,
         "created_by": user["id"], "created_at": now()}
    prompts_db.data.insert(0, p)
    prompts_db.save()
    return ok(p)


@router.patch("/prompts/{pid}")
async def update_prompt(pid: str, body: dict, user: dict = Depends(current_user)):
    p = _owned_prompt(pid, user)
    for k in ("name", "content", "category", "starred"):
        if k in body:
            p[k] = body[k]
    prompts_db.save()
    return ok(p)


@router.delete("/prompts/{pid}")
async def delete_prompt(pid: str, user: dict = Depends(current_user)):
    _owned_prompt(pid, user)
    prompts_db.data = [p for p in prompts_db.data if p["id"] != pid]
    prompts_db.save()
    return ok(None)


# ---------- 管理后台 ----------

@router.get("/admin/users", dependencies=[Depends(require_admin)])
async def admin_users():
    out = []
    for u in users_db.data:
        out.append({
            **public_user(u),
            "username": u.get("username") or u.get("email") or u["logto_id"],
            "agent_count": sum(1 for a in agents_db.data if a.get("created_by") == u["id"]),
        })
    return ok(out)


@router.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: str, body: dict, admin: dict = Depends(require_admin)):
    u = find(users_db.data, id=user_id)
    if not u:
        raise HTTPException(404, detail=err(40400, "用户不存在"))
    if u["id"] == admin["id"] and body.get("status") == "disabled":
        raise HTTPException(400, detail=err(40000, "不能禁用自己"))
    if body.get("status") in ("active", "disabled"):
        u["status"] = body["status"]
    if body.get("role") in ("user", "admin"):
        u["role"] = body["role"]
    users_db.save()
    return ok(public_user(u))


@router.get("/admin/stats/usage", dependencies=[Depends(require_admin)])
async def usage_stats():
    daily = [{"date": d, "calls": c} for d, c in sorted(stats_db.data["daily_calls"].items())]
    return ok(daily[-14:])


@router.get("/admin/stats/models", dependencies=[Depends(require_admin)])
async def model_stats():
    return ok([{"name": k.split("/", 1)[-1], "value": v}
               for k, v in sorted(stats_db.data["model_calls"].items(), key=lambda x: -x[1])])

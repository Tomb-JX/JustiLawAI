"""鉴权：Logto OIDC JWT 校验 + 本地用户建档（对齐 api-contract.md §1.3）。

两种启用模式（配置了 LOGTO_ENDPOINT 才启用鉴权）：
- resource 模式：LOGTO_API_RESOURCE 已配 → 校验面向 API 的 access token（Logto 付费功能）
- idtoken 模式：只配了 LOGTO_APP_ID → 前端直传 ID Token，按 aud=app_id 校验。
  Logto 免费版无法创建 API Resource 时的等效保护：签名（JWKS）/iss/aud/exp 全验，
  权衡是 ID Token 同时面向客户端，适合小规模部署，升级 Pro 后切回 resource 模式只需加一个环境变量。

未配置 LOGTO_ENDPOINT：单用户本地模式，所有请求视为本地管理员（便于离线开发与演示）。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from . import config
from .resp import err
from .store import find, now, uid, users_db

AUTH_ENABLED = bool(config.LOGTO_ENDPOINT)
ISSUER = f"{config.LOGTO_ENDPOINT.rstrip('/')}/oidc"
# resource 模式校 aud=API Resource；idtoken 模式校 aud=应用 client_id
AUDIENCE = config.LOGTO_API_RESOURCE or config.LOGTO_APP_ID
LOCAL_SUB = "local"

_jwks_client = None


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient

        # 公钥缓存在进程内，Logto 轮换密钥时按 kid 自动重新拉取
        _jwks_client = PyJWKClient(f"{ISSUER}/jwks", cache_keys=True)
    return _jwks_client


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(401, detail=err(40100, message))


def _upsert_user(sub: str, scopes: set[str]) -> dict:
    user = find(users_db.data, logto_id=sub)
    is_admin = sub == LOCAL_SUB or sub in config.ADMIN_SUBS or "admin" in scopes
    if not user:
        user = {
            "id": uid("u"), "logto_id": sub,
            "username": None, "nickname": "本地用户" if sub == LOCAL_SUB else f"用户{sub[-6:]}",
            "email": None, "avatar": None,
            "role": "admin" if is_admin else "user", "status": "active",
            "created_at": now(), "last_active_at": now(), "call_count": 0,
        }
        users_db.data.append(user)
    else:
        user["last_active_at"] = now()
        if is_admin:
            user["role"] = "admin"
    users_db.save()
    return user


def current_user(request: Request) -> dict:
    """FastAPI 依赖：返回本地用户记录。同步函数，FastAPI 会放到线程池执行（JWKS 拉取是阻塞 IO）。"""
    if not AUTH_ENABLED:
        return _upsert_user(LOCAL_SUB, set())

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise _unauthorized("未登录")
    token = header[7:].strip()

    import jwt

    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key,
            algorithms=["ES384", "ES256", "RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("登录已过期")
    except Exception as e:
        raise _unauthorized(f"token 无效：{e}")

    # roles 数组在 ID Token 里（UserScope.Roles），scope 字符串在 access token 里
    scopes = set((claims.get("scope") or "").split()) | set(claims.get("roles") or [])
    user = _upsert_user(claims["sub"], scopes)
    if user.get("status") == "disabled":
        raise HTTPException(403, detail=err(40300, "账号已被禁用"))
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, detail=err(40300, "需要管理员权限"))
    return user


def public_user(user: dict) -> dict:
    return {k: user.get(k) for k in
            ("id", "logto_id", "username", "nickname", "email", "avatar", "role", "status",
             "created_at", "last_active_at", "call_count")}

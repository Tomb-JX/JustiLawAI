"""裁量能力层的模型槽位（设计文档 discretion-capability-layer.md §3）。

配置存 settings_db["discretion"]["models"][slot] = {model_id, fallback_model_id, params}，
model_id 为空时用平台默认对话模型。只能选平台已登记、带 completion 能力的模型。
提示随代码版本走，不在配置里改（保证可复现）。
"""
from __future__ import annotations

import copy

from ..model_gateway.gateway import provider_store
from ..store import settings_db

SLOTS = {
    "segment": {"title": "分段与结果解析（S1 链路）",
                "params": {"temperature": 0, "max_tokens": 4000, "seed": 20261028, "thinking": False,
                           "timeout_s": 180, "retries": 1}},
    "extract": {"title": "要素抽取（要素链路）",
                "params": {"temperature": 0, "max_tokens": 8000, "seed": 20261028, "thinking": False,
                           "timeout_s": 300, "retries": 1}},
}
PARAM_KEYS = {"temperature", "top_p", "max_tokens", "seed", "thinking", "timeout_s", "retries", "extra_body"}


def _stored() -> dict:
    return (settings_db.data.get("discretion") or {}).get("models") or {}


def _completion_ids() -> set[str]:
    return {m["id"] for m in provider_store.all_models("completion")}


def get() -> dict:
    out = {}
    for slot, d in SLOTS.items():
        s = _stored().get(slot) or {}
        out[slot] = {"title": d["title"], "model_id": s.get("model_id"),
                     "effective_model_id": s.get("model_id") or provider_store.default_model("chat"),
                     "fallback_model_id": s.get("fallback_model_id"),
                     "params": {**d["params"], **(s.get("params") or {})},
                     "allow_user_override": bool(s.get("allow_user_override", False))}
    return out


def put(patch: dict) -> dict:
    """patch = {slot: {model_id?, fallback_model_id?, params?, allow_user_override?}}；返回错误列表为空才保存。"""
    errors, models, ids = [], copy.deepcopy(_stored()), _completion_ids()
    for slot, v in (patch or {}).items():
        if slot not in SLOTS:
            errors.append(f"未知槽位：{slot}")
            continue
        cur = models.setdefault(slot, {})
        for key in ("model_id", "fallback_model_id"):
            if key in v:
                if v[key] and v[key] not in ids:
                    errors.append(f"{slot}.{key}：{v[key]} 不是已登记的对话模型")
                cur[key] = v[key] or None
        if "params" in v:
            bad = set(v["params"] or {}) - PARAM_KEYS
            if bad:
                errors.append(f"{slot}.params 含不支持的参数：{'、'.join(sorted(bad))}")
            cur["params"] = {k: x for k, x in (v["params"] or {}).items() if k in PARAM_KEYS}
        if "allow_user_override" in v:
            cur["allow_user_override"] = bool(v["allow_user_override"])
    if not errors:
        settings_db.data.setdefault("discretion", {})["models"] = models
        settings_db.save()
    return {"errors": errors, "settings": get()}


def resolve(slot: str, override: str | None, user: dict) -> dict:
    """单次调用实际使用的配置。普通用户只有在槽位允许时才能临时换模型。"""
    cfg = get()[slot]
    if override:
        if user.get("role") != "admin" and not cfg["allow_user_override"]:
            raise PermissionError(f"槽位 {slot} 不允许临时指定模型")
        if override not in _completion_ids():
            raise LookupError(f"{override} 不是已登记的对话模型")
        cfg = {**cfg, "effective_model_id": override}
    if not cfg["effective_model_id"]:
        raise LookupError("裁量模型未配置，且平台没有可用的默认对话模型")
    return cfg

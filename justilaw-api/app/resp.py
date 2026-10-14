"""统一响应包：{ code, message, data }（对齐 docs/02-design/api-contract.md）"""
from typing import Any


def ok(data: Any = None):
    return {"code": 0, "message": "ok", "data": data}


def err(code: int, message: str):
    return {"code": code, "message": message, "data": None}

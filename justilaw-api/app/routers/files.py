"""通用文件上传（对话附件）：保存文件，首次使用时解析文本并缓存。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import config
from ..auth import current_user
from ..rag.pipeline import parse_file
from ..resp import err, ok
from ..store import files_db, now, save_upload, uid

router = APIRouter()
log = logging.getLogger("justilaw.files")


@router.post("/files")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(current_user)):
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(422, detail=err(42200, f"文件超过 {config.MAX_UPLOAD_MB}MB 限制"))
    name = file.filename or "untitled"
    path = save_upload(data, name)
    fid = uid("f")
    files_db.data[fid] = {"filename": name, "size": len(data), "path": str(path),
                          "owner_id": user["id"], "created_at": now()}
    files_db.save()
    return ok({"file_id": fid, "filename": name, "size": len(data)})


def attachment_text(file_id: str, user: dict) -> str:
    """返回附件可注入上下文的文本；无权限、不存在或无法解析时返回提示文字而不是抛错。"""
    meta = files_db.data.get(file_id)
    if not meta or (meta.get("owner_id") != user["id"] and user["role"] != "admin"):
        return ""
    if "text" not in meta:
        try:
            meta["text"] = parse_file(Path(meta["path"]))
        except Exception as e:
            log.info("附件解析失败 %s：%s", file_id, e)
            meta["text"] = f"（附件无法解析为文本：{e}）"
        files_db.save()
    return meta["text"]

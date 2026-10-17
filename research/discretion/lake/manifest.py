"""清单（manifest）写入与内容寻址 id（T-L1）。

manifest 本身也内容寻址：规范 JSON 的 SHA-256 决定 artifact id 与文件名。
Windows 文件名不能含冒号，因此 artifact id 使用 kind-hash16，而不是 kind:hash16。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

MANIFEST_VERSION = "1.0"


class ManifestError(RuntimeError):
    """清单缺失、版本不符或哈希不匹配。"""


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_kind(kind: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in kind) or "artifact"


def artifact_id(kind: str, sha256: str) -> str:
    if len(sha256) != 64:
        raise ValueError(f"非法 sha256：{sha256!r}")
    return f"{safe_kind(kind)}-{sha256[:16]}"


@dataclass(frozen=True)
class ManifestRef:
    artifact_id: str
    sha256: str
    path: Path


def write_manifest(lake_root: Path | str, kind: str, manifest: dict) -> ManifestRef:
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestError(
            f"manifest_version 必须是 {MANIFEST_VERSION}，实际 {manifest.get('manifest_version')!r}")
    payload = canonical_json_bytes(manifest)
    sha = sha256_bytes(payload)
    aid = artifact_id(kind, sha)
    path = Path(lake_root) / "ops" / "manifests" / f"{aid}.json"
    if path.exists():
        if file_sha256(path) != sha:
            raise ManifestError(f"artifact 路径已存在但哈希不同：{path}")
        return ManifestRef(aid, sha, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".manifest-", suffix=".tmp", delete=False
    ) as fh:
        tmp = Path(fh.name)
        fh.write(payload)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return ManifestRef(aid, sha, path)


def read_manifest(path: Path | str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestError(f"清单版本不符：{path}")
    return data


def iter_manifests(lake_root: Path | str) -> Iterator[Path]:
    root = Path(lake_root) / "ops" / "manifests"
    if not root.exists():
        return
    yield from sorted(root.glob("*.json"))

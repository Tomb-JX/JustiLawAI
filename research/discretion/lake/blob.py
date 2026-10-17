"""内容寻址 blob 存储（T-L1）。

路径：<lake>/blobs/sha256/<前两位>/<sha256>.zst
哈希：对未压缩字节计算 SHA-256；zstd 只影响存储，不影响键。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import zstandard as zstd

DEFAULT_LEVEL = 3


class BlobError(RuntimeError):
    """blob 读写错误基类。"""


class BlobMissing(BlobError):
    """blob 不存在。"""


class BlobCorrupt(BlobError):
    """解压后哈希与键不一致。"""


@dataclass(frozen=True)
class BlobRef:
    sha256: str
    path: Path
    size_raw: int
    size_zst: int
    media_type: str = "application/octet-stream"


class BlobStore:
    def __init__(self, lake_root: Path | str):
        self.lake_root = Path(lake_root)
        self.base = self.lake_root / "blobs" / "sha256"

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def path_for(self, sha256: str) -> Path:
        if len(sha256) != 64:
            raise ValueError(f"非法 sha256：{sha256!r}")
        return self.base / sha256[:2] / f"{sha256}.zst"

    def put_bytes(self, data: bytes, *, media_type: str = "application/octet-stream") -> BlobRef:
        sha = self.sha256_bytes(data)
        path = self.path_for(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            compressed = zstd.ZstdCompressor(level=DEFAULT_LEVEL).compress(data)
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".blob-", suffix=".tmp", delete=False
            ) as fh:
                tmp = Path(fh.name)
                fh.write(compressed)
            try:
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        return BlobRef(sha, path, len(data), path.stat().st_size, media_type)

    def put_text(self, text: str, *, encoding: str = "utf-8",
                 media_type: str = "text/plain; charset=utf-8") -> BlobRef:
        return self.put_bytes(text.encode(encoding), media_type=media_type)

    def get_bytes(self, sha256: str) -> bytes:
        path = self.path_for(sha256)
        if not path.exists():
            raise BlobMissing(f"blob 不存在：{sha256}")
        data = path.read_bytes()
        try:
            data = zstd.ZstdDecompressor().decompress(data)
        except zstd.ZstdError as exc:
            raise BlobCorrupt(f"blob 解压失败：{sha256}") from exc
        if self.sha256_bytes(data) != sha256:
            raise BlobCorrupt(f"blob 哈希不匹配：{sha256}")
        return data

    def get_text(self, sha256: str, *, encoding: str = "utf-8") -> str:
        return self.get_bytes(sha256).decode(encoding)

    def verify(self, sha256: str) -> list[str]:
        try:
            self.get_bytes(sha256)
            return []
        except BlobError as exc:
            return [str(exc)]

    def iter_hashes(self) -> Iterator[str]:
        if not self.base.exists():
            return
        for path in sorted(self.base.glob("*/*.zst")):
            yield path.stem

    def stats(self) -> dict:
        n = total_zst = 0
        for path in self.base.glob("*/*.zst") if self.base.exists() else []:
            n += 1
            total_zst += path.stat().st_size
        return {"blobs": n, "bytes_zst": total_zst}

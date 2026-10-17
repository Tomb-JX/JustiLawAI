"""数据湖全量校验（T-L1）。

检查：
1. 所有 blob 可解压且哈希一致；
2. 所有 manifest 的 outputs 文件存在且哈希一致；
3. 所有 records 的 text_sha256 可解析、record_hash 可复算；
4. catalog 缺失 blob 的引用（如 catalog 存在）。

用法：
  PYTHONPATH=research/discretion python -m lake.verify --lake "$DATA/lake"
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from .blob import BlobError, BlobStore
from .manifest import (canonical_json_bytes, file_sha256, iter_manifests,
                       read_manifest, sha256_bytes)


def _resolve(lake_root: Path, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path(lake_root) / p


def record_hash(rec: dict) -> str:
    payload = {k: v for k, v in rec.items() if k != "record_hash"}
    return sha256_bytes(canonical_json_bytes(payload))


def verify_records_file(lake_root: Path, path: Path, store: BlobStore) -> tuple[int, list[str]]:
    errors: list[str] = []
    n = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        n += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{lineno} JSON 解析失败：{exc}")
            continue
        rid = rec.get("id") or rec.get("record_id") or f"line{lineno}"
        h = rec.get("record_hash")
        if not h:
            errors.append(f"{path}:{lineno} {rid} 缺 record_hash")
        elif record_hash(rec) != h:
            errors.append(f"{path}:{lineno} {rid} record_hash 不匹配")
        sha = rec.get("text_sha256")
        if not sha:
            errors.append(f"{path}:{lineno} {rid} 缺 text_sha256")
            continue
        if not store.path_for(sha).exists():
            errors.append(f"{path}:{lineno} {rid} 引用的 blob 不存在：{sha}")
            continue
        try:
            data = store.get_bytes(sha)
        except BlobError as exc:
            errors.append(f"{path}:{lineno} {rid} blob 不可读：{exc}")
            continue
        if "text_len" in rec and rec["text_len"] != len(data):
            errors.append(f"{path}:{lineno} {rid} text_len={rec['text_len']} 实际={len(data)}")
    return n, errors


def verify_manifest(lake_root: Path, path: Path, store: BlobStore) -> tuple[int, list[str]]:
    errors: list[str] = []
    try:
        manifest = read_manifest(path)
    except Exception as exc:  # noqa: BLE001
        return 0, [f"{path} manifest 读取失败：{exc}"]
    records = 0
    for out in manifest.get("outputs", []):
        p = _resolve(lake_root, out.get("path", ""))
        if not p.exists():
            errors.append(f"{path} output 不存在：{p}")
            continue
        if out.get("sha256") and file_sha256(p) != out["sha256"]:
            errors.append(f"{path} output 哈希不匹配：{p}")
        if out.get("kind") == "records":
            n, errs = verify_records_file(lake_root, p, store)
            records += n
            errors += errs
    for blob in manifest.get("blobs", []):
        sha = blob.get("sha256", "")
        if not sha:
            errors.append(f"{path} blobs 缺少 sha256")
            continue
        p = store.path_for(sha)
        if not p.exists():
            errors.append(f"{path} 引用的 blob 不存在：{sha}")
            continue
        if blob.get("size_zst") is not None and p.stat().st_size != blob["size_zst"]:
            errors.append(f"{path} blob 压缩大小不符：{sha}")
        errors += store.verify(sha)
    return records, errors


def verify_all(lake_root: Path | str) -> dict:
    lake_root = Path(lake_root)
    store = BlobStore(lake_root)
    summary = {
        "lake_root": str(lake_root),
        "blobs": 0,
        "blob_errors": [],
        "manifests": 0,
        "manifest_errors": [],
        "records": 0,
        "record_errors": [],
        "catalog": {},
    }
    for sha in store.iter_hashes():
        summary["blobs"] += 1
        summary["blob_errors"] += store.verify(sha)
    seen_records: set[str] = set()
    for path in iter_manifests(lake_root):
        summary["manifests"] += 1
        try:
            manifest = read_manifest(path)
        except Exception as exc:  # noqa: BLE001
            summary["manifest_errors"].append(f"{path} manifest 读取失败：{exc}")
            continue
        n, errs = verify_manifest(lake_root, path, store)
        # 同一 records 文件可能被多个 manifest 引用（重跑/历史版本）：只计一次
        for out in manifest.get("outputs", []):
            if out.get("kind") == "records":
                key = str(_resolve(lake_root, out.get("path", "")).resolve())
                if key in seen_records:
                    n = 0
                else:
                    seen_records.add(key)
        summary["records"] += n
        summary["manifest_errors"] += errs
    db = lake_root / "catalog" / "lake.db"
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            for table in ("artifacts", "batches", "documents", "records", "lineage"):
                try:
                    summary["catalog"][table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error as exc:
                    summary["manifest_errors"].append(f"catalog {table}: {exc}")
            try:
                rows = conn.execute(
                    """SELECT batch_id, record_id FROM records r
                       WHERE text_clean_sha256 IS NOT NULL
                         AND NOT EXISTS (SELECT 1 FROM artifacts a
                                         WHERE a.kind='blob' AND a.sha256=r.text_clean_sha256)"""
                ).fetchall()
                summary["record_errors"] += [
                    f"catalog 缺 blob：{b}/{r}" for b, r in rows
                ]
            except sqlite3.Error as exc:
                summary["manifest_errors"].append(f"catalog 查询失败：{exc}")
        finally:
            conn.close()
    summary["ok"] = not (summary["blob_errors"] or summary["manifest_errors"]
                          or summary["record_errors"])
    return summary


def default_lake() -> Path:
    root = os.environ.get("JUSTILAW_DATA_DIR") or "D:/02_Dev/Data/justilaw-research"
    return Path(root) / "lake"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="数据湖全量校验")
    ap.add_argument("--lake", default=str(default_lake()))
    args = ap.parse_args(argv)
    summary = verify_all(args.lake)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

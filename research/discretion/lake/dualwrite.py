"""parsed-1 批次 → lake 双写（T-L1）。

只读旧批次，不改原文件；在 lake 下写：
- blobs：每条 text_full 的内容寻址 zstd；
- 轻记录：去掉 text_full，改存 text_sha256/text_len；
- manifest + SQLite catalog（文档/记录/血缘）。

用法（仓库根目录）：
  PYTHONPATH=research/discretion python -m lake.dualwrite \
    --records "$DATA/parsed/pkulaw/merged-20261017-full/records.jsonl" \
    --source pkulaw --batch merged-20261017-full
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import __version__
from .blob import BlobStore
from .catalog import Catalog, now_iso
from .manifest import (MANIFEST_VERSION, artifact_id, canonical_json_bytes,
                       file_sha256, sha256_bytes, write_manifest)


def record_hash(rec: dict) -> str:
    payload = {k: v for k, v in rec.items() if k != "record_hash"}
    return sha256_bytes(canonical_json_bytes(payload))


def _rel(lake_root: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(lake_root).resolve()))
    except ValueError:
        return str(path)


def dualwrite_batch(lake_root: Path | str, source: str, batch: str,
                    records_path: Path | str, *, force: bool = False,
                    producer: str = "lake.dualwrite") -> dict:
    lake_root = Path(lake_root)
    records_path = Path(records_path)
    out_dir = lake_root / "parsed" / source / batch
    out_records = out_dir / "records.jsonl"
    if out_records.exists() and not force:
        raise FileExistsError(f"lake 记录已存在：{out_records}（--force 覆盖）")

    raw_records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
    if not raw_records:
        raise ValueError(f"空批次：{records_path}")

    store = BlobStore(lake_root)
    blobs = {}
    lake_records: list[dict] = []
    tiers = Counter()
    text_bytes = 0
    for rec in raw_records:
        text = rec.get("text_full") or ""
        data = text.encode("utf-8")
        ref = store.put_text(text)
        blobs.setdefault(ref.sha256, ref)
        lr = dict(rec)
        lr.pop("text_full", None)
        lr["text_sha256"] = ref.sha256
        lr["text_len"] = len(data)
        lr["text_encoding"] = "utf-8"
        lr["record_hash"] = record_hash(lr)
        lake_records.append(lr)
        tiers[(rec.get("quality") or {}).get("tier", "?")] += 1
        text_bytes += len(data)

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=out_dir,
        prefix=".records-", suffix=".tmp", delete=False
    ) as fh:
        tmp = Path(fh.name)
        for lr in lake_records:
            fh.write(json.dumps(lr, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
    os.replace(tmp, out_records)

    created = now_iso()
    # manifest 的 created_at 取源文件 mtime，保证同一输入重跑得到同一 manifest id
    manifest_created = datetime.fromtimestamp(
        records_path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    input_sha = file_sha256(records_path)
    input_bytes = records_path.stat().st_size
    output_sha = file_sha256(out_records)
    output_bytes = out_records.stat().st_size
    blobs_list = [
        {"sha256": sha, "path": _rel(lake_root, ref.path),
         "size_raw": ref.size_raw, "size_zst": ref.size_zst}
        for sha, ref in sorted(blobs.items())
    ]
    versions = {
        "parser": raw_records[0].get("parser", ""),
        "record_version": raw_records[0].get("record_version", ""),
        "clean": None,
    }
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "kind": "batch",
        "batch_id": batch,
        "source": source,
        "created_at": manifest_created,
        "producer": {"name": producer, "version": __version__},
        "inputs": [{"path": str(records_path), "sha256": input_sha, "bytes": input_bytes}],
        "outputs": [{"kind": "records", "path": _rel(lake_root, out_records),
                     "sha256": output_sha, "records": len(lake_records),
                     "bytes": output_bytes}],
        "blobs": blobs_list,
        "versions": versions,
        "counts": {
            "records": len(lake_records),
            "unique_texts": len(blobs),
            "text_bytes": text_bytes,
            "zst_bytes": sum(ref.size_zst for ref in blobs.values()),
            "by_tier": dict(tiers),
        },
        "status": "published",
    }
    mref = write_manifest(lake_root, "batch", manifest)

    cat = Catalog(lake_root / "catalog" / "lake.db")
    try:
        input_aid = artifact_id("input", input_sha)
        cat.upsert_artifact(input_aid, "input", input_sha, str(records_path), input_bytes,
                            producer=producer, version=__version__, created_at=created)
        output_aid = artifact_id("records", output_sha)
        cat.upsert_artifact(output_aid, "records", output_sha,
                            _rel(lake_root, out_records), output_bytes,
                            parents=[input_aid], producer=producer,
                            version=__version__, created_at=created)
        cat.add_lineage(output_aid, input_aid, "derived_from")
        for sha, ref in blobs.items():
            cat.upsert_artifact(artifact_id("blob", sha), "blob", sha,
                                _rel(lake_root, ref.path), ref.size_zst,
                                producer=producer, version=__version__, created_at=created)
        cat.upsert_artifact(mref.artifact_id, "manifest", mref.sha256,
                            _rel(lake_root, mref.path), mref.path.stat().st_size,
                            parents=[input_aid, output_aid], producer=producer,
                            version=__version__, created_at=created)
        cat.add_lineage(mref.artifact_id, input_aid, "input")
        cat.add_lineage(mref.artifact_id, output_aid, "output")
        cat.upsert_batch(batch, source, mref.sha256, len(lake_records), created_at=created)
        for i, (lr, orig) in enumerate(zip(lake_records, raw_records)):
            doc_id = lr.get("id") or f"{batch}-row-{i}"
            cat.upsert_document(
                doc_id, source,
                source_ref=lr.get("source_ref", ""),
                doc_no_hash=lr.get("doc_no_hash", ""),
                authority=lr.get("authority", ""),
                region_code=lr.get("region", ""),
                behavior_date=lr.get("behavior_date") or "",
                decision_date=lr.get("decision_date") or "",
                law_version=lr.get("law_version") or "",
                text_orig_sha256=lr.get("text_sha256", ""),
                meta={"batch": batch, "source_type": lr.get("source_type", ""),
                      "pkulaw_id": (orig.get("extra") or {}).get("pkulaw_id", "")},
            )
            cat.add_record(
                batch, doc_id,
                doc_id=doc_id,
                tier=(lr.get("quality") or {}).get("tier", ""),
                outcome_type=(lr.get("outcome") or {}).get("type", ""),
                event_id=lr.get("event_id", "") or lr.get("event_key", ""),
                text_clean_sha256=None,
                record_hash=lr["record_hash"],
                record_path=_rel(lake_root, out_records),
            )
        cat.commit()
        counts = cat.counts()
    finally:
        cat.close()

    return {
        "batch": batch,
        "source": source,
        "records": len(lake_records),
        "unique_texts": len(blobs),
        "text_bytes": text_bytes,
        "zst_bytes": sum(ref.size_zst for ref in blobs.values()),
        "manifest": mref.artifact_id,
        "manifest_sha": mref.sha256,
        "manifest_path": str(mref.path),
        "lake_records": str(out_records),
        "catalog": counts,
    }


def default_lake() -> Path:
    root = os.environ.get("JUSTILAW_DATA_DIR") or "D:/02_Dev/Data/justilaw-research"
    return Path(root) / "lake"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="parsed-1 批次 → lake 双写")
    ap.add_argument("--records", required=True, help="源 parsed-1 records.jsonl")
    ap.add_argument("--source", default="pkulaw", help="来源（pkulaw/web/...）")
    ap.add_argument("--batch", default="", help="批次 id（缺省取源文件父目录名）")
    ap.add_argument("--lake", default=str(default_lake()), help="lake 根目录")
    ap.add_argument("--force", action="store_true", help="覆盖已有 lake 记录")
    args = ap.parse_args(argv)
    batch = args.batch or Path(args.records).parent.name
    result = dualwrite_batch(args.lake, args.source, batch, args.records, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

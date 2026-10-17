"""T-L1 单测：blob / manifest / catalog / dualwrite / verify。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lake.blob import BlobCorrupt, BlobStore  # noqa: E402
from lake.catalog import Catalog  # noqa: E402
from lake.dualwrite import dualwrite_batch, record_hash  # noqa: E402
from lake.manifest import artifact_id, iter_manifests, read_manifest, write_manifest  # noqa: E402
from lake.verify import record_hash as verify_record_hash, verify_all  # noqa: E402


def _rec(i: int, text: str) -> dict:
    return {
        "id": f"P-{i:03d}",
        "record_version": "parsed-1",
        "parser": "pkulaw_ingest.py@0.3",
        "source_type": "处罚决定书",
        "source_ref": "法宝引证码 CLI.ALE.TEST",
        "doc_no_hash": "abc123",
        "behavior_date": "2026-01-02",
        "decision_date": "2026-01-03",
        "authority": "某市公安局",
        "region": "",
        "province": "某省",
        "law_version": "新法",
        "text_full": text,
        "outcome": {"type": "罚款", "fine": 500},
        "quality": {"tier": "L1-金标候选", "in_scope": True},
        "event_key": "E-test",
        "segments": {"text_facts": [0, min(8, len(text))]},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


def test_blob_roundtrip_and_dedupe(tmp_path):
    store = BlobStore(tmp_path / "lake")
    a = store.put_text("同一篇正文")
    b = store.put_text("同一篇正文")
    assert a.sha256 == b.sha256
    assert store.get_text(a.sha256) == "同一篇正文"
    assert store.stats()["blobs"] == 1
    assert store.verify(a.sha256) == []


def test_blob_corrupt_detected(tmp_path):
    store = BlobStore(tmp_path / "lake")
    ref = store.put_text("正文")
    ref.path.write_bytes(b"not-zstd")
    errors = store.verify(ref.sha256)
    assert errors and ("哈希" in errors[0] or "解压" in errors[0] or "zstd" in errors[0].lower())


def test_manifest_safe_id_and_roundtrip(tmp_path):
    ref = write_manifest(tmp_path / "lake", "batch", {
        "manifest_version": "1.0", "kind": "batch", "batch_id": "b-test",
        "created_at": "2026-10-18T00:00:00+08:00",
    })
    assert ":" not in ref.artifact_id
    assert ref.path.exists()
    assert read_manifest(ref.path)["batch_id"] == "b-test"
    assert list(iter_manifests(tmp_path / "lake")) == [ref.path]


def test_dualwrite_catalog_and_verify(tmp_path):
    lake = tmp_path / "lake"
    source = tmp_path / "records.jsonl"
    _write_jsonl(source, [_rec(1, "同一篇正文"), _rec(2, "同一篇正文")])
    result = dualwrite_batch(lake, "pkulaw", "batch-test", source)
    assert result["records"] == 2
    assert result["unique_texts"] == 1

    out = lake / "parsed" / "pkulaw" / "batch-test" / "records.jsonl"
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert "text_full" not in rows[0]
    assert rows[0]["text_sha256"] == rows[1]["text_sha256"]
    assert record_hash(rows[0]) == rows[0]["record_hash"]
    assert verify_record_hash(rows[0]) == rows[0]["record_hash"]

    with Catalog(lake / "catalog" / "lake.db") as cat:
        counts = cat.counts()
    assert counts["records"] == 2
    assert counts["documents"] == 2
    assert counts["batches"] == 1
    assert counts["artifacts"] >= 3  # input + blob + manifest

    report = verify_all(lake)
    assert report["ok"], report
    assert report["blobs"] == 1
    assert report["manifests"] == 1
    assert report["records"] == 2


def test_dualwrite_refuses_overwrite(tmp_path):
    lake = tmp_path / "lake"
    source = tmp_path / "records.jsonl"
    _write_jsonl(source, [_rec(1, "正文")])
    dualwrite_batch(lake, "pkulaw", "b", source)
    try:
        dualwrite_batch(lake, "pkulaw", "b", source)
    except FileExistsError:
        pass
    else:
        raise AssertionError("应拒绝覆盖")

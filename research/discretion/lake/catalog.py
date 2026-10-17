"""SQLite 目录与血缘（T-L1）。

只存元数据，不存正文；正文在 blob。SQLite 负责事务/查询，DuckDB/Parquet
负责后续分析视图（见设计 §9）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  path TEXT,
  bytes INTEGER,
  parents TEXT,
  producer TEXT,
  version TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
  batch_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  manifest_sha TEXT NOT NULL,
  records INTEGER,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_ref TEXT,
  doc_no_hash TEXT,
  authority TEXT,
  region_code TEXT,
  behavior_date TEXT,
  decision_date TEXT,
  law_version TEXT,
  text_orig_sha256 TEXT,
  meta TEXT
);

CREATE TABLE IF NOT EXISTS records (
  batch_id TEXT NOT NULL,
  record_id TEXT NOT NULL,
  doc_id TEXT,
  tier TEXT,
  outcome_type TEXT,
  event_id TEXT,
  text_clean_sha256 TEXT,
  record_hash TEXT NOT NULL,
  record_path TEXT NOT NULL,
  PRIMARY KEY (batch_id, record_id)
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  model TEXT,
  prompt_version TEXT,
  input_batch TEXT,
  manifest_sha TEXT,
  status TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS deliveries (
  version TEXT PRIMARY KEY,
  manifest_sha TEXT NOT NULL,
  records INTEGER,
  status TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS lineage (
  child_id TEXT NOT NULL,
  parent_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  PRIMARY KEY (child_id, parent_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_sha ON artifacts(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_docno ON documents(doc_no_hash);
CREATE INDEX IF NOT EXISTS idx_documents_region ON documents(region_code);
CREATE INDEX IF NOT EXISTS idx_records_id ON records(record_id);
CREATE INDEX IF NOT EXISTS idx_records_event ON records(event_id);
CREATE INDEX IF NOT EXISTS idx_records_text ON records(text_clean_sha256);

CREATE VIEW IF NOT EXISTS v_missing_blob AS
SELECT r.batch_id, r.record_id, r.text_clean_sha256
FROM records r
WHERE r.text_clean_sha256 IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM artifacts a
    WHERE a.kind = 'blob' AND a.sha256 = r.text_clean_sha256
  );

INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', 'lake-catalog-1');
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Catalog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(DDL)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upsert_artifact(self, artifact_id: str, kind: str, sha256: str, path: str,
                        bytes_: int, *, parents: Iterable[str] | None = None,
                        producer: str = "", version: str = "",
                        created_at: str | None = None, status: str = "current") -> None:
        self.conn.execute(
            """INSERT INTO artifacts
               (artifact_id, kind, sha256, path, bytes, parents, producer, version, created_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(artifact_id) DO UPDATE SET
                 kind=excluded.kind, sha256=excluded.sha256, path=excluded.path,
                 bytes=excluded.bytes, parents=excluded.parents, producer=excluded.producer,
                 version=excluded.version, status=excluded.status""",
            (artifact_id, kind, sha256, path, bytes_,
             json.dumps(list(parents or []), ensure_ascii=False),
             producer, version, created_at or now_iso(), status),
        )

    def upsert_batch(self, batch_id: str, source: str, manifest_sha: str,
                     records: int, *, status: str = "published",
                     created_at: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO batches(batch_id, source, manifest_sha, records, status, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(batch_id) DO UPDATE SET
                 source=excluded.source, manifest_sha=excluded.manifest_sha,
                 records=excluded.records, status=excluded.status""",
            (batch_id, source, manifest_sha, records, status, created_at or now_iso()),
        )

    def upsert_document(self, doc_id: str, source: str, *, source_ref: str = "",
                        doc_no_hash: str = "", authority: str = "", region_code: str = "",
                        behavior_date: str = "", decision_date: str = "",
                        law_version: str = "", text_orig_sha256: str = "",
                        meta: dict | None = None) -> None:
        self.conn.execute(
            """INSERT INTO documents
               (doc_id, source, source_ref, doc_no_hash, authority, region_code,
                behavior_date, decision_date, law_version, text_orig_sha256, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(doc_id) DO UPDATE SET
                 source=excluded.source, source_ref=excluded.source_ref,
                 doc_no_hash=excluded.doc_no_hash, authority=excluded.authority,
                 region_code=excluded.region_code, behavior_date=excluded.behavior_date,
                 decision_date=excluded.decision_date, law_version=excluded.law_version,
                 text_orig_sha256=excluded.text_orig_sha256, meta=excluded.meta""",
            (doc_id, source, source_ref, doc_no_hash, authority, region_code,
             behavior_date, decision_date, law_version, text_orig_sha256,
             json.dumps(meta or {}, ensure_ascii=False, sort_keys=True)),
        )

    def add_record(self, batch_id: str, record_id: str, *, doc_id: str = "",
                   tier: str = "", outcome_type: str = "", event_id: str = "",
                   text_clean_sha256: str | None = None, record_hash: str,
                   record_path: str) -> None:
        self.conn.execute(
            """INSERT INTO records
               (batch_id, record_id, doc_id, tier, outcome_type, event_id,
                text_clean_sha256, record_hash, record_path)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(batch_id, record_id) DO UPDATE SET
                 doc_id=excluded.doc_id, tier=excluded.tier,
                 outcome_type=excluded.outcome_type, event_id=excluded.event_id,
                 text_clean_sha256=excluded.text_clean_sha256,
                 record_hash=excluded.record_hash, record_path=excluded.record_path""",
            (batch_id, record_id, doc_id, tier, outcome_type, event_id,
             text_clean_sha256, record_hash, record_path),
        )

    def add_lineage(self, child_id: str, parent_id: str, relation: str = "input") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO lineage(child_id, parent_id, relation) VALUES (?,?,?)",
            (child_id, parent_id, relation),
        )

    def counts(self) -> dict:
        out = {}
        for table in ("artifacts", "batches", "documents", "records", "runs", "deliveries", "lineage"):
            out[table] = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return out

    def commit(self) -> None:
        self.conn.commit()

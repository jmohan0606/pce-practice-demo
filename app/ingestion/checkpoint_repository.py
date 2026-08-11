from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.ingestion.models import IngestionBatchStatus, IngestionStatus
from app.ingestion.sqlite_manager import SQLiteManager


class CheckpointRepository:
    def __init__(self) -> None:
        self.db = SQLiteManager()
        self.initialize()

    def initialize(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS phx_dm_pce_ingestion_batch (
                    batch_id TEXT PRIMARY KEY,
                    entity_name TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_records INTEGER DEFAULT 0,
                    processed_records INTEGER DEFAULT 0,
                    created_records INTEGER DEFAULT 0,
                    updated_records INTEGER DEFAULT 0,
                    skipped_records INTEGER DEFAULT 0,
                    failed_records INTEGER DEFAULT 0,
                    last_processed_row INTEGER DEFAULT 0,
                    progress_percent REAL DEFAULT 0,
                    message TEXT,
                    started_at TEXT,
                    updated_at TEXT
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS phx_dm_pce_ingestion_record_hash (
                    entity_name TEXT NOT NULL,
                    primary_key TEXT NOT NULL,
                    row_hash TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (entity_name, primary_key)
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS phx_dm_pce_ingestion_error (
                    error_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    row_number INTEGER,
                    primary_key TEXT,
                    error_message TEXT,
                    raw_record_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            conn.commit()

    def save_batch(self, status: IngestionBatchStatus) -> None:
        with self.db.connect() as conn:
            conn.execute(
                '''
                INSERT INTO phx_dm_pce_ingestion_batch (
                    batch_id, entity_name, file_name, status, total_records,
                    processed_records, created_records, updated_records,
                    skipped_records, failed_records, last_processed_row,
                    progress_percent, message, started_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    status=excluded.status,
                    total_records=excluded.total_records,
                    processed_records=excluded.processed_records,
                    created_records=excluded.created_records,
                    updated_records=excluded.updated_records,
                    skipped_records=excluded.skipped_records,
                    failed_records=excluded.failed_records,
                    last_processed_row=excluded.last_processed_row,
                    progress_percent=excluded.progress_percent,
                    message=excluded.message,
                    updated_at=excluded.updated_at
                ''',
                (
                    status.batch_id,
                    status.entity_name,
                    status.file_name,
                    status.status.value,
                    status.total_records,
                    status.processed_records,
                    status.created_records,
                    status.updated_records,
                    status.skipped_records,
                    status.failed_records,
                    status.last_processed_row,
                    status.progress_percent,
                    status.message,
                    status.started_at.isoformat(),
                    status.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def latest_batch(self, entity_name: str, file_name: str) -> IngestionBatchStatus | None:
        rows = self.db.query(
            '''
            SELECT * FROM phx_dm_pce_ingestion_batch
            WHERE entity_name = ? AND file_name = ?
            ORDER BY updated_at DESC
            LIMIT 1
            ''',
            (entity_name, file_name),
        )
        if not rows:
            return None
        row = rows[0]
        return IngestionBatchStatus(
            batch_id=row["batch_id"],
            entity_name=row["entity_name"],
            file_name=row["file_name"],
            status=IngestionStatus(row["status"]),
            total_records=row["total_records"],
            processed_records=row["processed_records"],
            created_records=row["created_records"],
            updated_records=row["updated_records"],
            skipped_records=row["skipped_records"],
            failed_records=row["failed_records"],
            last_processed_row=row["last_processed_row"],
            progress_percent=row["progress_percent"],
            message=row["message"],
            started_at=datetime.fromisoformat(row["started_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_hash(self, entity_name: str, primary_key: str) -> str | None:
        rows = self.db.query(
            "SELECT row_hash FROM phx_dm_pce_ingestion_record_hash WHERE entity_name = ? AND primary_key = ?",
            (entity_name, primary_key),
        )
        return rows[0]["row_hash"] if rows else None

    def get_hashes(self, entity_name: str) -> dict[str, str]:
        """All known row hashes for an entity in one read — lets a full-file run do
        delta detection without a SQLite round-trip per row."""
        rows = self.db.query(
            "SELECT primary_key, row_hash FROM phx_dm_pce_ingestion_record_hash WHERE entity_name = ?",
            (entity_name,),
        )
        return {row["primary_key"]: row["row_hash"] for row in rows}

    def upsert_hashes(self, entity_name: str, items: list[tuple[str, str]]) -> None:
        """Bulk hash upsert in one transaction (one fsync for the whole batch)."""
        if not items:
            return
        with self.db.connect() as conn:
            conn.executemany(
                '''
                INSERT INTO phx_dm_pce_ingestion_record_hash (entity_name, primary_key, row_hash, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(entity_name, primary_key) DO UPDATE SET
                    row_hash=excluded.row_hash,
                    updated_at=CURRENT_TIMESTAMP
                ''',
                [(entity_name, pk, h) for pk, h in items],
            )
            conn.commit()

    def upsert_hash(self, entity_name: str, primary_key: str, row_hash: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                '''
                INSERT INTO phx_dm_pce_ingestion_record_hash (entity_name, primary_key, row_hash, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(entity_name, primary_key) DO UPDATE SET
                    row_hash=excluded.row_hash,
                    updated_at=CURRENT_TIMESTAMP
                ''',
                (entity_name, primary_key, row_hash),
            )
            conn.commit()

    def save_error(
        self,
        error_id: str,
        batch_id: str,
        entity_name: str,
        row_number: int,
        primary_key: str | None,
        error_message: str,
        raw_record: dict[str, Any],
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                '''
                INSERT INTO phx_dm_pce_ingestion_error (
                    error_id, batch_id, entity_name, row_number,
                    primary_key, error_message, raw_record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    error_id,
                    batch_id,
                    entity_name,
                    row_number,
                    primary_key,
                    error_message,
                    json.dumps(raw_record),
                ),
            )
            conn.commit()

    def list_errors(self, entity_name: str | None = None, limit: int = 50) -> list[dict]:
        """Persisted per-row/per-batch errors, newest first — errors must
        survive a page refresh."""
        if entity_name:
            return self.db.query(
                "SELECT * FROM phx_dm_pce_ingestion_error WHERE entity_name = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (entity_name, limit),
            )
        return self.db.query(
            "SELECT * FROM phx_dm_pce_ingestion_error ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    def clear_entity(self, entity_name: str) -> None:
        """Drop the row hashes and batch checkpoints for an entity after its data
        is deleted — a stale checkpoint must never suppress a real re-load."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM phx_dm_pce_ingestion_record_hash WHERE entity_name = ?", (entity_name,))
            conn.execute("DELETE FROM phx_dm_pce_ingestion_batch WHERE entity_name = ?", (entity_name,))
            conn.commit()

    def list_batches(self, limit: int = 50) -> list[dict]:
        return self.db.query(
            "SELECT * FROM phx_dm_pce_ingestion_batch ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )

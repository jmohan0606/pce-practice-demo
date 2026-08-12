"""Round G task 5 — shared base for the durable SQLite layer.

The graph mirror is process-local in mock mode (FoundationGraphStore), so the
rule store and the insight store each keep a durable SQLite file under
``data/runtime/`` (gitignored) holding their FULL dicts as JSON. The graph
mirror stays exactly as it is — the live-TigerGraph path — and SQLite is the
local durability layer alongside it (precedent: ``app/ingestion/sqlite_manager``
for the access style, Round E ``document_chunks`` for "fail loudly, never serve
empty").

DB path resolution (test databases / re-runs):
- ``<ENV_VAR>``            explicit file path for one store's db
- ``PCE_RUNTIME_DB_DIR``   directory for all runtime dbs (verify scripts point
                           this at a temp dir so each run starts fresh)
- default                  ``data/runtime/<name>`` anchored at the repo root
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config.settings import resolve_app_path


class PersistenceError(RuntimeError):
    """A persisted record exists but cannot be fully rehydrated. Raised loudly —
    an empty or partial result is never silently served (Round E precedent)."""


def runtime_db_path(env_var: str, default_name: str) -> Path:
    explicit = os.environ.get(env_var)
    if explicit:
        path = resolve_app_path(explicit)
    else:
        directory = os.environ.get("PCE_RUNTIME_DB_DIR") or "data/runtime"
        path = resolve_app_path(directory) / default_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class SqliteJsonDb:
    """One file db, dict rows, JSON-blob payload tables. Every operation opens
    its own connection (thread-safe: the app persists from daemon batch
    threads); writes go through ``transaction()`` so a run and its child rows
    land atomically."""

    def __init__(self, db_path: Path, ddl: tuple[str, ...]) -> None:
        self.db_path = str(db_path)
        with self.transaction() as conn:
            for stmt in ddl:
                conn.execute(stmt)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

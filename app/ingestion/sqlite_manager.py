from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.config.settings import get_settings, resolve_app_path


class SQLiteManager:
    """Thin SQLite access used by the ingestion checkpoint repository.
    One file DB (SQLITE_DB_PATH), dict rows."""

    def __init__(self, db_path: str | None = None) -> None:
        # Anchored at the repo root so the live DB never depends on launch dir.
        if db_path is None:
            self.db_path = str(get_settings().resolved_sqlite_db_path)
        else:
            self.db_path = str(resolve_app_path(db_path))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, params)
            conn.commit()

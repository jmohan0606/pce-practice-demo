"""Round G task 5.4 — durable SQLite layer for the rule store.

Round F showed compiled plans dying with the process (the graph mirror is
process-local in mock mode). Every rule/version write now also lands here as
the FULL dict — plan, scopes, plan_by_scope, statement, citations, all
lifecycle fields — and the store rehydrates from this file at construction, so
``ensure_v0_seed`` sees the rehydrated version and stays a no-op.

Fail-loudly contract: a corrupt persisted row raises ``PersistenceError`` at
rehydration — a partial rule set is never silently served.

DB: ``data/runtime/rule_store.db`` (gitignored); override with
``PCE_RULE_DB_PATH`` or ``PCE_RUNTIME_DB_DIR`` (see sqlite_persistence).
"""
from __future__ import annotations

import json

from app.shared.sqlite_persistence import PersistenceError, SqliteJsonDb, runtime_db_path

_DDL = (
    """CREATE TABLE IF NOT EXISTS rule (
        rule_key TEXT PRIMARY KEY,
        rule_json TEXT NOT NULL,
        persisted_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS rule_set_version (
        version_id TEXT PRIMARY KEY,
        version_json TEXT NOT NULL,
        persisted_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
)


class RuleStorePersistence:
    def __init__(self, db_path=None) -> None:
        self.db = SqliteJsonDb(
            db_path or runtime_db_path("PCE_RULE_DB_PATH", "rule_store.db"), _DDL)

    def save_rule(self, rule: dict) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO rule (rule_key, rule_json) VALUES (?, ?) "
                "ON CONFLICT(rule_key) DO UPDATE SET rule_json = excluded.rule_json, "
                "persisted_at = datetime('now')",
                (rule["rule_key"], json.dumps(rule, default=str)))

    def save_version(self, version: dict) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO rule_set_version (version_id, version_json) VALUES (?, ?) "
                "ON CONFLICT(version_id) DO UPDATE SET version_json = excluded.version_json, "
                "persisted_at = datetime('now')",
                (version["version_id"], json.dumps(version, default=str)))

    def save_draft_seq(self, value: int) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('draft_seq', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(value),))

    def load_all(self) -> tuple[dict[str, dict], dict[str, dict], int]:
        """(rules by rule_key, versions by version_id, draft_seq). Raises
        PersistenceError on any corrupt row — never a partial rule set."""
        rules: dict[str, dict] = {}
        versions: dict[str, dict] = {}
        for table, key_col, json_col, bucket in (
                ("rule", "rule_key", "rule_json", rules),
                ("rule_set_version", "version_id", "version_json", versions)):
            for row in self.db.query(f"SELECT * FROM {table}"):  # noqa: S608 — fixed names
                try:
                    payload = json.loads(row[json_col])
                except (TypeError, ValueError) as exc:
                    raise PersistenceError(
                        f"{table} row {row[key_col]!r} is persisted but corrupt: {exc}"
                    ) from exc
                if not isinstance(payload, dict) or payload.get(key_col) != row[key_col]:
                    raise PersistenceError(
                        f"{table} row {row[key_col]!r} payload does not match its key")
                bucket[row[key_col]] = payload
        seq_rows = self.db.query("SELECT value FROM meta WHERE key = 'draft_seq'")
        draft_seq = int(seq_rows[0]["value"]) if seq_rows else 0
        return rules, versions, draft_seq

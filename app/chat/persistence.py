"""Round E Task 4 — durable SQLite layer for chat conversations.

Write-through: the ChatStore persists every mutation (create / rename /
add_message / delete) as it happens, and rehydrates the whole store on
construction, so conversations and messages survive a process restart — the
rehydration is what lets the agent resolve "her" against a message from three
days ago (Task 5). Precedent: ``app/insights/run_persistence.py`` — same
``data/runtime/`` resolution (gitignored), same fail-loudly contract.

Global persistence for now — every user sees every conversation (deliberate
demo simplification, recorded in DECISIONS.md; per-user scoping comes later).

DB: ``data/runtime/chat.db``; override with ``PCE_CHAT_DB_PATH`` or
``PCE_RUNTIME_DB_DIR`` (see sqlite_persistence).
"""
from __future__ import annotations

import json

from app.shared.logging import get_logger
from app.shared.sqlite_persistence import PersistenceError, SqliteJsonDb, runtime_db_path

_log = get_logger("app.chat.persistence")

_DDL = (
    """CREATE TABLE IF NOT EXISTS conversation (
        conversation_id TEXT PRIMARY KEY,
        row_json TEXT NOT NULL,
        persisted_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS chat_message (
        conversation_id TEXT NOT NULL,
        seq_no INTEGER NOT NULL,
        row_json TEXT NOT NULL,
        PRIMARY KEY (conversation_id, seq_no)
    )""",
)


class ChatPersistence:
    def __init__(self, db_path=None) -> None:
        self.db = SqliteJsonDb(
            db_path or runtime_db_path("PCE_CHAT_DB_PATH", "chat.db"), _DDL)

    # ------------------------------------------------------------------ writes

    def save_conversation(self, row: dict) -> None:
        """Upsert one conversation header (create / rename / message-count bump)."""
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversation (conversation_id, row_json) VALUES (?, ?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET "
                "row_json=excluded.row_json, persisted_at=datetime('now')",
                (row["conversation_id"], json.dumps(row, default=str)))

    def save_message(self, conversation_row: dict, message_row: dict) -> None:
        """Persist one message AND its updated conversation header atomically —
        a message never lands without the header's message_count/updated_at."""
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_message (conversation_id, seq_no, row_json) "
                "VALUES (?, ?, ?)",
                (message_row["conversation_id"], int(message_row["seq_no"]),
                 json.dumps(message_row, default=str)))
            conn.execute(
                "INSERT INTO conversation (conversation_id, row_json) VALUES (?, ?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET "
                "row_json=excluded.row_json, persisted_at=datetime('now')",
                (conversation_row["conversation_id"],
                 json.dumps(conversation_row, default=str)))

    def delete_conversation(self, conversation_id: str) -> None:
        """Delete the conversation and ALL its messages — the messages go with
        it (Task 5)."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM chat_message WHERE conversation_id = ?",
                         (conversation_id,))
            conn.execute("DELETE FROM conversation WHERE conversation_id = ?",
                         (conversation_id,))

    # ------------------------------------------------------------------- reads

    def load_all(self) -> tuple[list[dict], dict[str, list[dict]]]:
        """(conversation rows, conversation_id -> ordered message rows) — the
        full durable state, rehydrated at store construction. Fail-loudly: a
        corrupt persisted row raises PersistenceError, never a silent skip."""
        conversations: list[dict] = []
        for r in self.db.query("SELECT conversation_id, row_json FROM conversation"):
            try:
                row = json.loads(r["row_json"])
            except (TypeError, ValueError) as exc:
                raise PersistenceError(
                    f"conversation {r['conversation_id']!r} is persisted but its "
                    f"row_json is corrupt: {exc}") from exc
            if not isinstance(row, dict) or row.get("conversation_id") != r["conversation_id"]:
                raise PersistenceError(
                    f"conversation {r['conversation_id']!r} is persisted but its "
                    f"payload does not match its key")
            conversations.append(row)
        messages: dict[str, list[dict]] = {}
        for r in self.db.query(
                "SELECT conversation_id, seq_no, row_json FROM chat_message "
                "ORDER BY conversation_id, seq_no"):
            try:
                row = json.loads(r["row_json"])
            except (TypeError, ValueError) as exc:
                raise PersistenceError(
                    f"chat message {r['conversation_id']!r}|{r['seq_no']} is persisted "
                    f"but its row_json is corrupt: {exc}") from exc
            messages.setdefault(r["conversation_id"], []).append(row)
        return conversations, messages

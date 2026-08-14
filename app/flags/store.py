"""Round A2B task 7 — durable feature-flag state.

Follows the app/rules/store.py pattern: a durable SQLite layer under
``data/runtime/`` (override with ``PCE_FLAGS_DB_PATH`` / ``PCE_RUNTIME_DB_DIR``)
is the source of truth, and every write MIRRORS the flag row to the graph as a
``phx_dm_pce_feature_flag`` vertex through the tiered graph client (the
app-written-vertex precedent: no CSV loading job — the runtime upsert IS the
loading job, like phx_dm_pce_agent_turn_log).

State: a flag missing from the table is ON (the default). Turning a flag off
requires a reason; the guardrail (always_on) cannot be turned off at all.
Every change lands in flag_history with who/when/reason.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.flags.registry import FLAGS, PRESETS
from app.shared.logging import get_logger
from app.shared.sqlite_persistence import SqliteJsonDb, runtime_db_path

_log = get_logger("app.flags.store")

FLAG_VERTEX = "phx_dm_pce_feature_flag"
_FLAG_GRAPH_ATTRS = ("flag_key", "enabled", "updated_at", "updated_by",
                     "note_reason", "note_at")

_DDL = (
    """CREATE TABLE IF NOT EXISTS flag (
        flag_key TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL,
        note_reason TEXT,
        note_by TEXT,
        note_at TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS flag_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        flag_key TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        by TEXT NOT NULL,
        reason TEXT NOT NULL
    )""",
)


class FlagStoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _graph_entry() -> dict:
    return {
        "kind": "vertex", "target": FLAG_VERTEX, "id_column": "flag_key",
        "file": f"runtime:{FLAG_VERTEX}",
        "columns": {name: name for name in _FLAG_GRAPH_ATTRS if name != "flag_key"},
    }


class FlagStore:
    def __init__(self, db_path=None) -> None:
        self._lock = threading.RLock()
        self.db = SqliteJsonDb(
            db_path or runtime_db_path("PCE_FLAGS_DB_PATH", "feature_flags.db"), _DDL)

    # ----- reads -----

    def _rows(self) -> dict[str, dict]:
        return {r["flag_key"]: r for r in self.db.query("SELECT * FROM flag")}

    def enabled(self, key: str) -> bool:
        """The flag's OWN switch state (default on)."""
        if key not in FLAGS:
            raise FlagStoreError(f"unknown feature flag '{key}'")
        row = self._rows().get(key)
        return True if row is None else bool(row["enabled"])

    def effective_enabled(self, key: str) -> bool:
        """Own state AND every ancestor's state — parent off means child off."""
        rows = self._rows()
        cursor: str | None = key
        while cursor:
            if cursor not in FLAGS:
                raise FlagStoreError(f"unknown feature flag '{cursor}'")
            row = rows.get(cursor)
            if row is not None and not bool(row["enabled"]):
                return False
            cursor = FLAGS[cursor]["parent"]
        return True

    def flag_note(self, key: str) -> dict | None:
        row = self._rows().get(key)
        if row is None or bool(row["enabled"]) or not row["note_reason"]:
            return None
        return {"when": row["note_at"], "by": row["note_by"],
                "reason": row["note_reason"]}

    def snapshot(self) -> list[dict]:
        """Serialized state for every registered flag, registry order."""
        rows = self._rows()
        out = []
        for key, meta in FLAGS.items():
            row = rows.get(key)
            enabled = True if row is None else bool(row["enabled"])
            out.append({
                "key": key, "enabled": enabled,
                "effective_enabled": self.effective_enabled(key),
                "note": self.flag_note(key),
                **{k: meta[k] for k in ("name", "description", "group",
                                        "parent", "always_on", "dep", "cost")},
            })
        return out

    def history(self, limit: int = 200) -> list[dict]:
        return [
            {"when": r["at"], "flag": r["flag_key"],
             "flag_name": FLAGS.get(r["flag_key"], {}).get("name", r["flag_key"]),
             "enabled": bool(r["enabled"]), "by": r["by"], "reason": r["reason"]}
            for r in self.db.query(
                "SELECT * FROM flag_history ORDER BY id DESC LIMIT ?", (int(limit),))
        ]

    # ----- writes -----

    def _mirror(self, key: str, row: dict) -> None:
        from app.graph.client import get_graph_client

        payload = {
            "flag_key": key, "enabled": bool(row["enabled"]),
            "updated_at": row["updated_at"], "updated_by": row["note_by"] or "",
            "note_reason": row["note_reason"] or "", "note_at": row["note_at"] or "",
        }
        try:
            get_graph_client().upsert(_graph_entry(), [payload])
        except Exception as exc:  # noqa: BLE001 — SQLite stays authoritative; log loudly
            _log.error("graph mirror of flag %s failed: %s", key, exc)

    def _write(self, conn, key: str, enabled: bool, by: str, reason: str) -> dict:
        now = _now()
        row = {"enabled": 1 if enabled else 0,
               "note_reason": None if enabled else reason,
               "note_by": None if enabled else by,
               "note_at": None if enabled else now,
               "updated_at": now}
        conn.execute(
            "INSERT INTO flag (flag_key, enabled, note_reason, note_by, note_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(flag_key) DO UPDATE SET "
            "enabled=excluded.enabled, note_reason=excluded.note_reason, "
            "note_by=excluded.note_by, note_at=excluded.note_at, "
            "updated_at=excluded.updated_at",
            (key, row["enabled"], row["note_reason"], row["note_by"],
             row["note_at"], row["updated_at"]))
        conn.execute(
            "INSERT INTO flag_history (at, flag_key, enabled, by, reason) "
            "VALUES (?, ?, ?, ?, ?)", (now, key, row["enabled"], by, reason))
        return row

    def set_flag(self, key: str, enabled: bool, by: str = "operator",
                 reason: str = "") -> dict:
        if key not in FLAGS:
            raise FlagStoreError(f"unknown feature flag '{key}'")
        if FLAGS[key]["always_on"] and not enabled:
            raise FlagStoreError(
                f"{key} is Always On and cannot be turned off — without it a "
                f"narrative could contain a figure nobody computed")
        if not enabled and not str(reason).strip():
            raise FlagStoreError(
                "a reason is required to turn a flag off — six weeks from now "
                "it is the only record of why the section disappeared")
        with self._lock:
            with self.db.transaction() as conn:
                row = self._write(conn, key, enabled, by,
                                  str(reason).strip() or ("turned on" if enabled else ""))
            self._mirror(key, row)
        return self.snapshot_one(key)

    def apply_preset(self, preset: str, by: str = "operator") -> list[dict]:
        """One click sets every flag; ONE history entry naming the preset."""
        meta = PRESETS.get(preset)
        if meta is None:
            raise FlagStoreError(
                f"unknown preset '{preset}' (expected {', '.join(PRESETS)})")
        off = meta["off"]
        now = _now()
        with self._lock:
            with self.db.transaction() as conn:
                rows: dict[str, dict] = {}
                for key, flag_meta in FLAGS.items():
                    enabled = flag_meta["always_on"] or key not in off
                    reason = "" if enabled else f"preset '{meta['name']}' applied"
                    row = {"enabled": 1 if enabled else 0,
                           "note_reason": None if enabled else reason,
                           "note_by": None if enabled else by,
                           "note_at": None if enabled else now,
                           "updated_at": now}
                    conn.execute(
                        "INSERT INTO flag (flag_key, enabled, note_reason, note_by, "
                        "note_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(flag_key) DO UPDATE SET enabled=excluded.enabled, "
                        "note_reason=excluded.note_reason, note_by=excluded.note_by, "
                        "note_at=excluded.note_at, updated_at=excluded.updated_at",
                        (key, row["enabled"], row["note_reason"], row["note_by"],
                         row["note_at"], row["updated_at"]))
                    rows[key] = row
                # ONE history entry naming the preset (7.4)
                conn.execute(
                    "INSERT INTO flag_history (at, flag_key, enabled, by, reason) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (now, "__preset__", 1, by,
                     f"preset '{meta['name']}' applied — "
                     f"{len(FLAGS) - len(off)} of {len(FLAGS)} on"))
            for key, row in rows.items():
                self._mirror(key, row)
        return self.snapshot()

    def snapshot_one(self, key: str) -> dict:
        return next(r for r in self.snapshot() if r["key"] == key)


_store: FlagStore | None = None
_store_lock = threading.Lock()


def get_flag_store() -> FlagStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = FlagStore()
        return _store


def reset_flag_store() -> None:
    global _store
    with _store_lock:
        _store = None

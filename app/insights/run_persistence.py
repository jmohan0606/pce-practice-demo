"""Round G task 5.4 — durable SQLite layer for insight runs.

Written at ``complete_run``/``fail_run`` (the FULL run dict, all findings with
their evidence rows, and the query/turn logs, in one transaction); rehydrated
by the store on a process-local miss. The graph mirror is untouched — this file
is what survives a restart in mock mode.

Fail-loudly contract: ``load()`` returns None only when the run_id was never
persisted. A run that IS indexed as persisted but whose payload is missing,
corrupt, or incomplete (finding rows ≠ the run's recorded finding_count) raises
``PersistenceError`` — an empty or partial run is never silently served.

DB: ``data/runtime/insight_runs.db`` (gitignored); override with
``PCE_INSIGHT_DB_PATH`` or ``PCE_RUNTIME_DB_DIR`` (see sqlite_persistence).
"""
from __future__ import annotations

import json

from app.shared.logging import get_logger
from app.shared.sqlite_persistence import PersistenceError, SqliteJsonDb, runtime_db_path

_log = get_logger("app.insights.run_persistence")

_DDL = (
    """CREATE TABLE IF NOT EXISTS insight_run (
        run_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        finding_count INTEGER NOT NULL,
        run_json TEXT NOT NULL,
        persisted_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS insight_finding (
        run_id TEXT NOT NULL,
        rank_order INTEGER NOT NULL,
        finding_json TEXT NOT NULL,
        PRIMARY KEY (run_id, rank_order)
    )""",
    """CREATE TABLE IF NOT EXISTS insight_log_row (
        run_id TEXT NOT NULL,
        kind TEXT NOT NULL,           -- 'query' | 'turn'
        seq_no INTEGER NOT NULL,
        row_json TEXT NOT NULL,
        PRIMARY KEY (run_id, kind, seq_no)
    )""",
)


def _clean_run(run: dict) -> dict:
    """The persisted run dict: everything except in-process-only fields
    (leading underscore, e.g. ``_t0``)."""
    return {k: v for k, v in run.items() if not k.startswith("_")}


class InsightRunPersistence:
    def __init__(self, db_path=None) -> None:
        self.db = SqliteJsonDb(
            db_path or runtime_db_path("PCE_INSIGHT_DB_PATH", "insight_runs.db"), _DDL)

    def save(self, run: dict, findings: list[dict], query_log: list[dict],
             turn_log: list[dict]) -> None:
        """Persist one run atomically. Re-saving the same run_id (supersede /
        regenerate) replaces the prior payload — the supersede history rides
        inside run_json, exactly as in the in-process dict."""
        run_id = run["run_id"]
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM insight_run WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM insight_finding WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM insight_log_row WHERE run_id = ?", (run_id,))
            conn.execute(
                "INSERT INTO insight_run (run_id, status, finding_count, run_json) "
                "VALUES (?, ?, ?, ?)",
                (run_id, run.get("status") or "", len(findings),
                 json.dumps(_clean_run(run), default=str)))
            for finding in findings:
                conn.execute(
                    "INSERT INTO insight_finding (run_id, rank_order, finding_json) "
                    "VALUES (?, ?, ?)",
                    (run_id, int(finding.get("rank_order") or 0),
                     json.dumps(finding, default=str)))
            for kind, rows in (("query", query_log), ("turn", turn_log)):
                for row in rows:
                    conn.execute(
                        "INSERT INTO insight_log_row (run_id, kind, seq_no, row_json) "
                        "VALUES (?, ?, ?, ?)",
                        (run_id, kind, int(row.get("seq_no") or 0),
                         json.dumps(row, default=str)))
        _log.info("persisted insight run %s (%d findings) to %s",
                  run_id, len(findings), self.db.db_path)

    def run_ids(self) -> list[str]:
        return [r["run_id"] for r in self.db.query("SELECT run_id FROM insight_run")]

    def load(self, run_id: str) -> tuple[dict, list[dict], list[dict], list[dict]] | None:
        """(run, findings, query_log, turn_log) — None ONLY if never persisted;
        PersistenceError if persisted but not fully rehydratable."""
        head = self.db.query(
            "SELECT run_id, finding_count, run_json FROM insight_run WHERE run_id = ?",
            (run_id,))
        if not head:
            return None
        try:
            run = json.loads(head[0]["run_json"])
        except (TypeError, ValueError) as exc:
            raise PersistenceError(
                f"insight run {run_id!r} is persisted but its run_json is corrupt: {exc}"
            ) from exc
        if not isinstance(run, dict) or run.get("run_id") != run_id:
            raise PersistenceError(
                f"insight run {run_id!r} is persisted but its payload does not match its key")
        finding_rows = self.db.query(
            "SELECT rank_order, finding_json FROM insight_finding WHERE run_id = ? "
            "ORDER BY rank_order", (run_id,))
        expected = int(head[0]["finding_count"])
        if len(finding_rows) != expected:
            raise PersistenceError(
                f"insight run {run_id!r} is persisted with finding_count={expected} but "
                f"only {len(finding_rows)} finding row(s) could be rehydrated — refusing "
                f"to serve a partial run")
        try:
            findings = [json.loads(r["finding_json"]) for r in finding_rows]
            log_rows = self.db.query(
                "SELECT kind, row_json FROM insight_log_row WHERE run_id = ? "
                "ORDER BY kind, seq_no", (run_id,))
            query_log = [json.loads(r["row_json"]) for r in log_rows if r["kind"] == "query"]
            turn_log = [json.loads(r["row_json"]) for r in log_rows if r["kind"] == "turn"]
        except (TypeError, ValueError) as exc:
            raise PersistenceError(
                f"insight run {run_id!r} is persisted but a child row is corrupt: {exc}"
            ) from exc
        return run, findings, query_log, turn_log

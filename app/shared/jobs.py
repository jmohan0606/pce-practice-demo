"""Round 1 (schema freeze) task 2 — resumable long-running work: the JobStore.

One ``phx_dm_pce_job`` row per long-running pipeline invocation (kinds:
document_ingest | insight_generation | data_load). The mechanism is simple and
deliberate: **each stage writes its output before the next begins**, so an
interrupted job resumes at the stage it died in — earlier stages' outputs are
already on disk and are never repeated. ``resume_token`` is opaque JSON: enough
to restart the CURRENT stage (e.g. the next extraction window index).

Statuses: RUNNING | INTERRUPTED | COMPLETE | FAILED.
Resume is EXPLICIT — an interrupted job is shown with a Resume action (UI is
Round 3); nothing auto-resumes on page load, which could double-spend.

Persistence follows the turn-log precedent for app-written vertices: durable
SQLite (``data/runtime/jobs.db``, override PCE_JOBS_DB_PATH) is authoritative;
every write mirrors the schema-catalogued subset to the graph — the runtime
upsert IS the loading job (no CSV load exists). Edges mirror when the scope is
known: ``phx_dm_pce_job_for_document`` (kind=document_ingest, scope_key is the
document_id) and ``phx_dm_pce_job_for_run`` (kind=insight_generation,
scope_key is the run_id).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from app.shared.logging import get_logger
from app.shared.sqlite_persistence import SqliteJsonDb, runtime_db_path

_log = get_logger("app.shared.jobs")

JOB_VERTEX = "phx_dm_pce_job"
JOB_FOR_DOCUMENT_EDGE = "phx_dm_pce_job_for_document"
JOB_FOR_RUN_EDGE = "phx_dm_pce_job_for_run"

JOB_KINDS = ("document_ingest", "insight_generation", "data_load")
JOB_STATUSES = ("RUNNING", "INTERRUPTED", "COMPLETE", "FAILED")

# The fixed stage lists per kind (ROUND_1_SCHEMA_FREEZE_SPEC task 2). data_load
# derives its stages from the manifest at begin_job time — one per entity.
STAGES_BY_KIND = {
    "document_ingest": ("parse", "chunk", "embed", "extract", "compile", "audit"),
    "insight_generation": ("evaluate_rules", "investigate_residual",
                           "narrate", "persist"),
}

_JOB_GRAPH_ATTRS = (
    "job_id", "kind", "scope_key", "stage", "stage_index", "stage_total",
    "items_done", "items_total", "status", "resume_token", "error",
    "started_at", "updated_at", "completed_at",
)

_DDL = (
    """CREATE TABLE IF NOT EXISTS job (
        job_id TEXT PRIMARY KEY,
        job_json TEXT NOT NULL,
        persisted_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _vertex_entry() -> dict:
    return {"kind": "vertex", "target": JOB_VERTEX, "id_column": "job_id",
            "file": f"runtime:{JOB_VERTEX}",
            "columns": {n: n for n in _JOB_GRAPH_ATTRS if n != "job_id"}}


def _edge_entry(edge: str, to_type: str) -> dict:
    return {"kind": "edge", "target": edge, "from_type": JOB_VERTEX,
            "to_type": to_type, "from_column": "from_id", "to_column": "to_id",
            "file": f"runtime:{edge}", "columns": {}}


class JobStoreError(RuntimeError):
    pass


class JobStore:
    """Durable job rows: SQLite write-through + graph mirror + edges."""

    def __init__(self, db_path=None) -> None:
        self._lock = threading.RLock()
        self.db = SqliteJsonDb(
            db_path or runtime_db_path("PCE_JOBS_DB_PATH", "jobs.db"), _DDL)

    # ------------------------------------------------------------- persistence

    def _save(self, job: dict) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO job (job_id, job_json) VALUES (?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET job_json = excluded.job_json, "
                "persisted_at = datetime('now')",
                (job["job_id"], json.dumps(job, default=str)))
        self._mirror(job)

    def _mirror(self, job: dict) -> None:
        row = {n: ("" if job.get(n) is None else job.get(n))
               for n in _JOB_GRAPH_ATTRS}
        row["resume_token"] = (json.dumps(job["resume_token"])
                               if isinstance(job.get("resume_token"), dict)
                               else (job.get("resume_token") or ""))
        try:
            graph = self._graph()
            graph.upsert(_vertex_entry(), [row])
            edge = None
            if job["kind"] == "document_ingest" and job.get("scope_key"):
                edge = (_edge_entry(JOB_FOR_DOCUMENT_EDGE, "phx_dm_pce_document"),
                        job["scope_key"])
            elif job["kind"] == "insight_generation" and job.get("run_id"):
                edge = (_edge_entry(JOB_FOR_RUN_EDGE, "phx_dm_pce_insight_run"),
                        job["run_id"])
            if edge:
                graph.upsert(edge[0], [{"from_id": job["job_id"],
                                        "to_id": edge[1]}])
        except Exception as exc:  # noqa: BLE001 — store stays authoritative; log loudly
            _log.error("graph mirror of job %s failed: %s", job.get("job_id"), exc)

    def _graph(self):
        from app.graph.client import get_graph_client

        return get_graph_client()

    # ------------------------------------------------------------------- reads

    def get(self, job_id: str) -> dict | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT job_json FROM job WHERE job_id = ?",
                               (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_jobs(self, kind: str | None = None,
                  scope_key: str | None = None) -> list[dict]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT job_json FROM job").fetchall()
        jobs = [json.loads(r[0]) for r in rows]
        if kind:
            jobs = [j for j in jobs if j.get("kind") == kind]
        if scope_key:
            jobs = [j for j in jobs if j.get("scope_key") == scope_key]
        return sorted(jobs, key=lambda j: j.get("started_at") or "", reverse=True)

    def latest_for(self, kind: str, scope_key: str) -> dict | None:
        jobs = self.list_jobs(kind=kind, scope_key=scope_key)
        return jobs[0] if jobs else None

    # ------------------------------------------------------------------ writes

    def begin_job(self, kind: str, scope_key: str,
                  stages: list[str] | tuple[str, ...] | None = None) -> dict:
        if kind not in JOB_KINDS:
            raise JobStoreError(f"unknown job kind {kind!r} — expected one of "
                                f"{', '.join(JOB_KINDS)}")
        stages = list(stages or STAGES_BY_KIND.get(kind) or ())
        if not stages:
            raise JobStoreError(f"kind {kind!r} needs an explicit stage list "
                                "(data_load: one stage per entity)")
        with self._lock:
            job = {
                "job_id": f"JOB_{uuid.uuid4().hex[:12]}",
                "kind": kind, "scope_key": scope_key,
                "stages": stages,  # SQLite-only; the graph carries the current stage
                "stage": stages[0], "stage_index": 1, "stage_total": len(stages),
                "items_done": 0, "items_total": 0,
                "status": "RUNNING", "resume_token": None, "error": "",
                "started_at": _now(), "updated_at": _now(), "completed_at": "",
            }
            self._save(job)
            return job

    def update(self, job_id: str, *, stage: str | None = None,
               scope_key: str | None = None, run_id: str | None = None,
               items_done: int | None = None, items_total: int | None = None,
               resume_token: dict | str | None = None,
               extra: dict | None = None) -> dict:
        """Advance the job: entering a stage means every earlier stage's output
        is already written. Per-item progress (items_done/items_total) applies
        within the CURRENT stage; resume_token must be enough to restart it.
        ``extra`` merges free-form keys into the job dict (SQLite-only —
        Round 7: the extraction funnel + limit live here)."""
        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise JobStoreError(f"unknown job_id {job_id!r}")
            if stage is not None:
                stages = job.get("stages") or []
                if stage not in stages:
                    raise JobStoreError(
                        f"stage {stage!r} is not one of {job_id}'s stages "
                        f"{stages}")
                if stages.index(stage) + 1 != job["stage_index"]:
                    # entering a new stage resets per-item progress
                    job.update(items_done=0, items_total=0, resume_token=None)
                job["stage"] = stage
                job["stage_index"] = stages.index(stage) + 1
            if scope_key is not None:
                job["scope_key"] = scope_key
            if run_id is not None:
                # SQLite-only field; drives the job_for_run edge mirror
                job["run_id"] = run_id
            if items_done is not None:
                job["items_done"] = int(items_done)
            if items_total is not None:
                job["items_total"] = int(items_total)
            if resume_token is not None:
                job["resume_token"] = resume_token
            if extra:
                job.update(extra)
            job["status"] = "RUNNING"
            job["updated_at"] = _now()
            self._save(job)
            return job

    def complete(self, job_id: str) -> dict:
        return self._finish(job_id, "COMPLETE")

    def fail(self, job_id: str, error: str) -> dict:
        return self._finish(job_id, "FAILED", error=error)

    def interrupt(self, job_id: str, resume_token: dict | str | None = None,
                  error: str = "") -> dict:
        """The job stopped before its work finished but CAN continue — the
        current stage's resume_token says where. Distinct from FAILED (a
        failed job's inputs need fixing before a rerun makes sense)."""
        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise JobStoreError(f"unknown job_id {job_id!r}")
            job["status"] = "INTERRUPTED"
            if resume_token is not None:
                job["resume_token"] = resume_token
            job["error"] = error or job.get("error") or ""
            job["updated_at"] = _now()
            self._save(job)
            return job

    def _finish(self, job_id: str, status: str, error: str = "") -> dict:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise JobStoreError(f"unknown job_id {job_id!r}")
            job["status"] = status
            job["error"] = error
            job["resume_token"] = None if status == "COMPLETE" else job.get("resume_token")
            job["updated_at"] = _now()
            job["completed_at"] = _now()
            self._save(job)
            return job


def touch_document_stage(document_id: str, stage: str) -> None:
    """Record that a demand-driven document_ingest stage (compile / audit) ran
    for this document. Per-stage granularity; the job returns to COMPLETE at
    the touched stage. A missing job (pre-Round-1 document) or a store error
    is logged, never raised — progress tracking must not break the pipeline."""
    try:
        store = get_job_store()
        job = store.latest_for("document_ingest", document_id)
        if job is None:
            return
        store.update(job["job_id"], stage=stage)
        store.complete(job["job_id"])
    except Exception as exc:  # noqa: BLE001
        _log.error("job stage touch (%s, %s) failed: %s", document_id, stage, exc)


_store: JobStore | None = None
_store_lock = threading.Lock()


def get_job_store() -> JobStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = JobStore()
        return _store


def reset_job_store() -> None:
    global _store
    with _store_lock:
        _store = None

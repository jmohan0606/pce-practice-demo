"""C4 — insight generation runs: one-advisor and all-advisors, async.

``run_insights_for_advisor`` is the synchronous unit: mine → report → persist.
``JobManager`` runs batches on a daemon thread, one advisor at a time, updating
progress after each; a failed advisor is marked failed WITH its error and the
batch continues — it never aborts the rest (C6 check 11).

advisor="all" expands to the aggregate book run (pseudo-advisor "all" — every
catalog query accepts it) followed by one run per cohort advisor. run_count in
the generate response is therefore cohort_size + 1 (decision recorded in
DECISIONS.md).
"""
from __future__ import annotations

import threading
import uuid

from app.agents.insights_miner import mine
from app.agents.insights_reporter import report
from app.graph.queries.catalog import run_catalog_query
from app.insights.store import get_insight_store
from app.insights.tools import MinerTools
from app.rules.seed import ensure_v0_seed
from app.rules.store import get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.insights.service")


def _resolve_llm(role: str):
    from app.llm.roles import build_role_llm

    role_llm = build_role_llm(role)
    if role_llm is not None:
        return role_llm.generate
    from app.llm.client import get_llm_client

    return get_llm_client().generate


def _published_version() -> dict:
    ensure_v0_seed()
    version = get_rule_store().latest_version("PUBLISHED")
    if version is None:
        raise RuntimeError("no PUBLISHED rule-set version exists")
    return version


def run_insights_for_advisor(advisor_sid: str, from_month: str, to_month: str,
                             version_id: str | None = None,
                             miner_llm=None, reporter_llm=None) -> dict:
    """Mine → report → persist one run. Returns the completed run dict
    (internal fields included — API layer strips them)."""
    version = (get_rule_store().version(version_id) if version_id
               else _published_version())
    if version is None:
        raise ValueError(f"unknown rule-set version {version_id!r}")
    store = get_insight_store()
    rules = [r for r in get_rule_store().version_rules(version["version_id"])
             if r.get("status") in ("PUBLISHED", "SUPERSEDED")]

    transition = run_catalog_query("advisor_totals", {
        "advisor": advisor_sid, "from_month": from_month, "to_month": to_month,
    })["rows"][0]

    run = store.begin_run(advisor_sid, from_month, to_month, version["version_id"])
    tools = MinerTools(run["run_id"])
    try:
        mined = mine(advisor_sid=advisor_sid, from_month=from_month, to_month=to_month,
                     rules=rules, transition=transition, tools=tools,
                     llm=miner_llm or _resolve_llm("insights_miner"))
        # C3: the Reporter receives FINDINGS ONLY (plus the transition totals,
        # themselves a stored query result on this run) and a text LLM callable.
        reported = report(mined["findings"], transition,
                          reporter_llm or _resolve_llm("insights_reporter"))
        completed = store.complete_run(
            run["run_id"], narrative=reported["narrative"], bullets=reported["bullets"],
            findings=mined["findings"], query_count=mined["query_count"],
            budget_hit=mined["budget_hit"], coverage_ratio=mined["coverage_ratio"])
        completed["unanswerable"] = mined["unanswerable"]
        completed["fallback_used"] = reported.get("fallback_used", False)
        return completed
    except Exception as exc:  # noqa: BLE001 — honest failure recorded on the run
        _log.exception("insight run %s failed", run["run_id"])
        return store.fail_run(run["run_id"], f"{type(exc).__name__}: {exc}")


def cohort_advisors() -> list[str]:
    rows = run_catalog_query("revenue_by_advisor",
                             {"month_id": _any_month()})["rows"]
    return [r["advisor_sid"] for r in rows]


def _any_month() -> str:
    from app.graph.foundation_store import get_foundation_store

    months = sorted(get_foundation_store().all_vertices("phx_dm_pce_month"))
    return months[0]


class JobManager:
    """Async batch runner. One daemon thread per job; one advisor at a time."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.jobs: dict[str, dict] = {}

    def start(self, advisor: str, from_month: str, to_month: str,
              version_id: str | None = None) -> dict:
        advisors = (["all", *cohort_advisors()] if advisor == "all" else [advisor])
        job_id = uuid.uuid4().hex[:12]
        job = {
            "job_id": job_id, "status": "running", "completed": 0,
            "total": len(advisors), "current": None,
            "runs": [{"run_id": None, "advisor_sid": sid, "status": "pending",
                      "finding_count": 0, "error": None} for sid in advisors],
            "from_month": from_month, "to_month": to_month,
        }
        with self._lock:
            self.jobs[job_id] = job
        thread = threading.Thread(
            target=self._run_job, args=(job_id, advisors, from_month, to_month, version_id),
            name=f"insights-{job_id}", daemon=True)
        thread.start()
        return {"job_id": job_id, "run_count": len(advisors)}

    def _run_job(self, job_id: str, advisors: list[str], from_month: str,
                 to_month: str, version_id: str | None) -> None:
        store = get_insight_store()
        for index, advisor_sid in enumerate(advisors):
            with self._lock:
                self.jobs[job_id]["current"] = advisor_sid
                self.jobs[job_id]["runs"][index]["status"] = "running"
            try:
                run = run_insights_for_advisor(advisor_sid, from_month, to_month,
                                               version_id)
                entry = {"run_id": run["run_id"], "status": run["status"].lower(),
                         "finding_count": len(store.run_findings(run["run_id"])),
                         "error": run.get("error")}
            except Exception as exc:  # noqa: BLE001 — a failed advisor never aborts the batch
                _log.exception("job %s: advisor %s failed", job_id, advisor_sid)
                entry = {"run_id": None, "status": "failed", "finding_count": 0,
                         "error": f"{type(exc).__name__}: {exc}"}
            with self._lock:
                job = self.jobs[job_id]
                job["runs"][index].update(entry)
                job["completed"] = index + 1
        with self._lock:
            job = self.jobs[job_id]
            job["current"] = None
            job["status"] = ("failed" if all(r["status"] == "failed" for r in job["runs"])
                             else "complete")

    def status(self, job_id: str) -> dict | None:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return {"status": job["status"], "completed": job["completed"],
                    "total": job["total"], "current": job["current"],
                    "runs": [dict(r) for r in job["runs"]]}


_jobs: JobManager | None = None
_jobs_lock = threading.Lock()


def get_job_manager() -> JobManager:
    global _jobs
    with _jobs_lock:
        if _jobs is None:
            _jobs = JobManager()
        return _jobs

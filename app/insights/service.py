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


def _resolve_llm_client(role: str):
    """The role's client OBJECT (not just .generate) so the turn-logging
    wrapper can read response.usage through generate_with_usage."""
    from app.llm.roles import build_role_llm

    role_llm = build_role_llm(role)
    if role_llm is not None:
        return role_llm
    from app.llm.client import get_llm_client

    return get_llm_client()


def _published_version() -> dict:
    ensure_v0_seed()
    version = get_rule_store().latest_version("PUBLISHED")
    if version is None:
        raise RuntimeError("no PUBLISHED rule-set version exists")
    return version


def _monetary_impact(rule: dict, matched: list[dict]) -> float | None:
    """Sum of matched values ONLY when the rule's compute aggregates a monetary
    field (name contains '_amt') — a count or a rate is not an impact figure
    and must never pollute the residual (DECISIONS.md, provisional)."""
    plan = rule.get("plan") or {}
    compute = plan.get("compute") or {}
    expr = str(compute.get("expr") or "")
    if compute.get("agg") == "sum" and "_amt" in expr:
        return round(sum(float(m.get("value") or 0) for m in matched), 2)
    return None


def evaluate_published_rules(advisor_sid: str, from_month: str, to_month: str,
                             version: dict) -> tuple[list[dict], list[dict]]:
    """Round E task 2 (provisional): evaluate every PUBLISHED rule for this
    advisor and transition through the evaluator — NO LLM; these are queries
    the AI already authored. Fired rules become pre-matched findings with
    rule_key, citation and evidence rows attached. Returns
    (rule_findings, rule_outcomes_for_the_prompt)."""
    from app.rules.service import evaluate_rule_set

    # Round G task 1: the aggregate book runs at practice scope — rules that
    # need an advisor either use their practice-scope plan variant or are
    # skipped as not applicable (never evaluated into an expected error).
    outcome = evaluate_rule_set(
        version["version_id"], month=to_month,
        advisor_sid=None if advisor_sid == "all" else advisor_sid,
        scope="practice" if advisor_sid == "all" else "advisor")
    rule_map = {r["rule_key"]: r
                for r in get_rule_store().version_rules(version["version_id"])}
    findings: list[dict] = []
    outcomes: list[dict] = []
    for result in outcome["results"]:
        rule = rule_map.get(result.get("rule_key")) or {}
        entry = {"rule_code": result.get("rule_code"),
                 "rule_key": result.get("rule_key"),
                 "evaluated": result.get("evaluated", False),
                 "matched_count": result.get("matched_count", 0),
                 "error": result.get("error"),
                 "empty_reason": result.get("empty_reason"),
                 "skipped": result.get("skipped", False),
                 "skip_reason": result.get("skip_reason")}
        outcomes.append(entry)
        matched = result.get("matched") or []
        if not (result.get("evaluated") and matched):
            continue
        impact = _monetary_impact(rule, matched)
        citations = rule.get("citations") or []
        # Round 3 task 2: no cap anywhere — the store keeps EVERY row behind
        # the number (sorted by contribution, footer totals attached).
        evidence_rows = list(matched)
        findings.append({
            "title": f"{rule.get('rule_name') or result.get('rule_code')} — "
                     f"{len(matched)} match(es) in {to_month}",
            "summary": (f"Rule {result.get('rule_code')} fired for "
                        f"{len(matched)} {rule.get('grain') or 'entity'}(s) in {to_month}. "
                        f"{rule.get('statement') or ''}").strip(),
            "impact_amt": impact,
            # Round A1 task 1: driver_code is the stored identity; driver_tag
            # here is the creation-time label for the reporter's prompt — the
            # store strips it, the API re-resolves it at read time.
            "driver_code": rule.get("driver_code") or "OTHER",
            "driver_tag": rule.get("driver_label") or rule.get("driver_tag") or "Other",
            "group_id": None,
            "rule_key": result.get("rule_key"),
            "provenance": "REAL",
            "confidence": 1.0,
            "evidence_columns": sorted(evidence_rows[0].keys()) if evidence_rows else [],
            "evidence_rows": evidence_rows,
            "evidence_reason": None,
            "citation": citations[0] if citations else None,
            "origin": "rule",
            "source_query": {"query_name": "rules_evaluate_plan",
                             "params": {"rule_code": result.get("rule_code"),
                                        "month": to_month,
                                        "advisor_sid": advisor_sid}},
        })
    return findings, outcomes


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
    # Round C (docs/rules) 2.1: an inactive rule feeds NOTHING into a new run —
    # neither evaluation (evaluate_rule_set skips it) nor the miner's context.
    live_rules = [r for r in get_rule_store().version_rules(version["version_id"])
                  if r.get("status") in ("PUBLISHED", "SUPERSEDED")
                  and r.get("active") is not False]
    # Round C (docs/rules) 5.2: natural-language-only rules are GUIDANCE — no
    # plan by design, never evaluated, never a computed figure. They ride the
    # miner's opening as clearly-labelled guidance, NOT the rule list (the two
    # kinds must never blur: a rule with a plan produces reproducible figures;
    # a natural-language rule shapes the agent's attention).
    from app.rules.service import natural_language_only

    nl_guidance = [r for r in live_rules if natural_language_only(r)]
    rules = [r for r in live_rules if not natural_language_only(r)]

    transition = run_catalog_query("advisor_totals", {
        "advisor": advisor_sid, "from_month": from_month, "to_month": to_month,
    })["rows"][0]

    # Round 1 (schema freeze) task 2 — one phx_dm_pce_job row per generation.
    # Stages: evaluate_rules → investigate_residual (per-item: miner turns) →
    # narrate → persist. Each stage's output is written before the next
    # begins; a FAILED job carries the error the run recorded.
    from app.shared.jobs import get_job_store

    jobs = get_job_store()
    job = jobs.begin_job("insight_generation",
                         f"{advisor_sid}|{from_month}->{to_month}")

    # Round E task 2 (PROVISIONAL — DECISIONS.md): rules evaluate in code before
    # the agent loop; the agent is pointed at the residual.
    try:
        rule_findings, rule_outcomes = evaluate_published_rules(
            advisor_sid, from_month, to_month, version)
    except Exception as exc:
        jobs.fail(job["job_id"], f"{type(exc).__name__}: {exc}")
        raise
    rule_impacts = sum(f["impact_amt"] for f in rule_findings
                       if f["impact_amt"] is not None)
    residual_amt = round(float(transition.get("change_amt") or 0.0) - rule_impacts, 2)

    run = store.begin_run(advisor_sid, from_month, to_month, version["version_id"])
    jobs.update(job["job_id"], stage="investigate_residual",
                scope_key=run["run_id"], run_id=run["run_id"])
    tools = MinerTools(run["run_id"])
    try:
        from app.llm.usage import wrap_llm

        # Every real LLM call is turn-logged (tokens from response.usage, cost,
        # latency). Explicit overrides (verify scripts) pass through unwrapped.
        miner = miner_llm or wrap_llm(_resolve_llm_client("insights_miner"),
                                      run["run_id"], "insights_miner")
        reporter = reporter_llm or wrap_llm(_resolve_llm_client("insights_reporter"),
                                            run["run_id"], "insights_reporter")
        mined = mine(advisor_sid=advisor_sid, from_month=from_month, to_month=to_month,
                     rules=rules, transition=transition, tools=tools, llm=miner,
                     rule_findings=rule_findings, rule_outcomes=rule_outcomes,
                     residual_amt=residual_amt, nl_guidance=nl_guidance,
                     on_turn=lambda done, total: jobs.update(
                         job["job_id"], items_done=done, items_total=total))
        jobs.update(job["job_id"], stage="narrate")
        # C3: the Reporter receives FINDINGS ONLY (plus the transition totals,
        # themselves a stored query result on this run) and a text LLM callable.
        # Round E task 5: plus ONE injected capability — document search for
        # thresholds (PLAN) and recommended practice (GUIDANCE) with citations,
        # so recommendations are fetched-and-cited, never recalled.
        from app.insights.reporter_sources import build_reporter_search

        reported = report(mined["findings"], transition, reporter,
                          search_documents=build_reporter_search(run["run_id"]))
        jobs.update(job["job_id"], stage="persist")
        agent_findings = [f for f in mined["findings"] if f.get("origin") != "rule"]
        agent_impacts = sum(abs(f["impact_amt"]) for f in agent_findings
                            if f["impact_amt"] is not None)
        residual_explained_pct = (round(agent_impacts / abs(residual_amt) * 100, 1)
                                  if residual_amt else None)
        completed = store.complete_run(
            run["run_id"], narrative=reported["narrative"], bullets=reported["bullets"],
            recommendations=reported.get("recommendations") or [],
            findings=mined["findings"], query_count=mined["query_count"],
            budget_hit=mined["budget_hit"],
            budget_hit_tokens=mined.get("budget_hit_tokens", False),
            limits_hit=mined.get("limits_hit") or [],
            coverage_ratio=mined["coverage_ratio"])
        completed["unanswerable"] = mined["unanswerable"]
        completed["fallback_used"] = reported.get("fallback_used", False)
        # Round E task 2 report-per-run figures
        completed["rule_findings"] = len(rule_findings)
        completed["agent_findings"] = len(agent_findings)
        completed["residual_amt"] = residual_amt
        completed["residual_explained_pct"] = residual_explained_pct
        completed["exploration_reserved"] = mined.get("exploration_reserved")
        jobs.complete(job["job_id"])
        return completed
    except Exception as exc:  # noqa: BLE001 — honest failure recorded on the run
        _log.exception("insight run %s failed", run["run_id"])
        jobs.fail(job["job_id"], f"{type(exc).__name__}: {exc}")
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

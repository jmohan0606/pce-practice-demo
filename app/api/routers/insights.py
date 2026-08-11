"""C4 — the insights API.

POST /api/insights/generate          {"advisor":"V…"|"all","from_month","to_month"}
GET  /api/insights/status/{job_id}
GET  /api/insights/query-log?run_id= (the agent's investigation trail)
GET  /api/insights/runs?from=&to=    (summary of runs for a transition)
GET  /api/insights/{advisor}/{from_month}/{to_month}?version=latest

The coverage ratio is an INTERNAL build-time signal (C2) — ``_serialize_run``
strips it from every response, and C6 check 12 asserts it stays absent.
Evidence rows are capped at 20 in responses (50 stored).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.insights.store import EVIDENCE_DISPLAY_CAP, get_insight_store
from app.insights.service import get_job_manager
from app.rules.store import get_rule_store

router = APIRouter(prefix="/api/insights", tags=["insights"])


class GenerateRequest(BaseModel):
    advisor: str = Field(..., description='advisor_sid or "all"')
    from_month: str
    to_month: str
    version_id: str | None = None


def _serialize_finding(finding: dict) -> dict:
    evidence = finding.get("evidence_rows") or []
    return {
        "finding_id": finding.get("finding_id"),
        "title": finding.get("title"), "summary": finding.get("summary"),
        "impact_amt": finding.get("impact_amt"),
        "driver_tag": finding.get("driver_tag"), "group_id": finding.get("group_id"),
        "rule_key": finding.get("rule_key"), "provenance": finding.get("provenance"),
        "confidence": finding.get("confidence"),
        "evidence_columns": finding.get("evidence_columns") or [],
        "evidence_rows": evidence[:EVIDENCE_DISPLAY_CAP],
        "evidence_total": len(evidence),
        "evidence_reason": finding.get("evidence_reason"),
        "source_query": finding.get("source_query"),
        "rank_order": finding.get("rank_order"),
    }


def _rule_citation(rule_key: str | None) -> dict | None:
    if not rule_key:
        return None
    rule = get_rule_store().get(rule_key)
    if rule is None:
        return None
    citations = rule.get("citations") or []
    return {"rule_key": rule_key, "rule_code": rule.get("rule_code"),
            "rule_name": rule.get("rule_name"),
            "citation": citations[0] if citations else None}


def _serialize_run(run: dict, findings: list[dict]) -> dict:
    """The API shape. coverage_ratio (internal) is DELIBERATELY absent."""
    import json as _json

    serialized = []
    for f in findings:
        row = _serialize_finding(f)
        row["rule_citation"] = _rule_citation(row["rule_key"])
        serialized.append(row)
    return {
        "run_id": run["run_id"], "advisor_sid": run["advisor_sid"],
        "from_month_id": run["from_month_id"], "to_month_id": run["to_month_id"],
        "version_id": run["version_id"], "status": run["status"],
        "narrative": run["narrative"],
        "bullets": _json.loads(run.get("bullets_json") or "[]"),
        "findings": serialized,
        "generated_at": run.get("completed_at") or run.get("started_at"),
        "query_count": run.get("query_count", 0),
        "budget_hit": bool(run.get("budget_hit")),
        "generation": run.get("generation", 1),
        "error": run.get("error"),
    }


@router.post("/generate")
def generate(body: GenerateRequest) -> dict:
    if body.version_id:
        version = get_rule_store().version(body.version_id)
        if version is None:
            raise HTTPException(404, f"unknown rule-set version '{body.version_id}'")
    return get_job_manager().start(body.advisor, body.from_month, body.to_month,
                                   body.version_id)


@router.get("/status/{job_id}")
def status(job_id: str) -> dict:
    result = get_job_manager().status(job_id)
    if result is None:
        raise HTTPException(404, f"unknown job '{job_id}'")
    return result


@router.get("/query-log")
def query_log(run_id: str) -> dict:
    store = get_insight_store()
    if store.run(run_id) is None:
        raise HTTPException(404, f"unknown run '{run_id}'")
    return {"run_id": run_id, "entries": store.run_query_log(run_id)}


@router.get("/peer-rank")
def peer_rank(advisor: str, month_id: str, metric: str = "credited_amt") -> dict:
    """The advisor's cohort rank on a metric — the C5 KPI row's 'rank in cohort'.
    Served by the peer_comparison catalog query (C1)."""
    from app.graph.queries.catalog import CatalogError, run_catalog_query

    try:
        rows = run_catalog_query("peer_comparison", {
            "advisor": advisor, "month_id": month_id, "metric": metric})["rows"]
        cohort = run_catalog_query("peer_comparison", {
            "advisor": "all", "month_id": month_id, "metric": metric})["rows"]
    except CatalogError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = rows[0] if rows else None
    return {"advisor_sid": advisor, "month_id": month_id, "metric": metric,
            "rank": row["rank"] if row else None,
            "cohort_size": len(cohort),
            "cohort_median": row["cohort_median"] if row else None}


@router.get("/runs")
def runs(from_month: str, to_month: str) -> dict:
    store = get_insight_store()
    rows = []
    for run in store.runs_for_transition(from_month, to_month):
        rows.append({"run_id": run["run_id"], "advisor_sid": run["advisor_sid"],
                     "version_id": run["version_id"], "status": run["status"],
                     "generated_at": run.get("completed_at") or run.get("started_at"),
                     "finding_count": len(store.run_findings(run["run_id"]))})
    return {"runs": sorted(rows, key=lambda r: r["advisor_sid"])}


@router.get("/{advisor}/{from_month}/{to_month}")
def get_insights(advisor: str, from_month: str, to_month: str,
                 version: str = "latest") -> dict:
    store = get_insight_store()
    version_id = None if version in ("", "latest") else version
    run = store.latest_run_for(advisor, from_month, to_month, version_id)
    if run is None:
        raise HTTPException(404, f"no insight run for {advisor} {from_month}->{to_month}"
                                 + (f" at version {version}" if version_id else ""))
    return _serialize_run(run, store.run_findings(run["run_id"]))

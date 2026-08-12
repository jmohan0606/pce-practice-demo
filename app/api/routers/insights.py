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
            # Round F 5.1: the driver chip's tooltip is the matched rule's
            # plain-English statement; the frontend falls back to its own
            # definition table only when a finding has no rule.
            "statement": rule.get("statement"),
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
        # Round E task 5: each carries a source_query or citation(s), asserted
        # in app/agents/insights_reporter.py before persistence
        "recommendations": _json.loads(run.get("recommendations_json") or "[]"),
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


@router.get("/practice-summary")
def practice_summary(from_month: str, to_month: str) -> dict:
    """KPI row for the practice view (Round E 6.2): credited revenue, AUM,
    net flows — every figure computed from graph data, nothing invented.
    (Open exceptions come from /exceptions; the UI counts those rows.)"""
    from app.graph.foundation_store import get_foundation_store
    from app.graph.queries.catalog import CatalogError, run_catalog_query

    store = get_foundation_store()
    months = store.all_vertices("phx_dm_pce_month")
    for label, mid in (("from_month", from_month), ("to_month", to_month)):
        if str(mid) not in months:
            raise HTTPException(404, f"unknown {label} '{mid}'")
    try:
        totals = run_catalog_query("advisor_totals", {
            "advisor": "all", "from_month": from_month, "to_month": to_month})["rows"][0]
    except CatalogError as exc:
        raise HTTPException(400, str(exc)) from exc

    cohort = {sid for sid, a in store.all_vertices("phx_dm_pce_advisor").items()
              if a.get("in_cohort") is True}

    def _f(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _aum(month_id: str) -> float:
        return round(sum(_f(r.get("end_balance"))
                         for r in store.all_vertices("phx_dm_pce_account_month").values()
                         if str(r.get("advisor_sid")) in cohort
                         and str(r.get("month_id")) == str(month_id)), 2)

    def _flows(month_id: str) -> dict:
        rows = [r for r in store.all_vertices("phx_dm_pce_advisor_flow_month").values()
                if str(r.get("advisor_sid")) in cohort
                and str(r.get("month_id")) == str(month_id)]
        return {"inflows": round(sum(_f(r.get("total_inflows")) for r in rows), 2),
                "outflows": round(sum(_f(r.get("total_outflows")) for r in rows), 2),
                "net_flows": round(sum(_f(r.get("total_net_flows")) for r in rows), 2)}

    aum_from, aum_to = _aum(from_month), _aum(to_month)
    aum_change = round(aum_to - aum_from, 2)
    return {
        "from_month_id": from_month, "to_month_id": to_month,
        "advisor_count": len(cohort),
        "credited": totals,  # {from_amt, to_amt, change_amt, change_pct}
        "aum": {"from_amt": aum_from, "to_amt": aum_to, "change_amt": aum_change,
                "change_pct": round(aum_change / aum_from * 100, 2) if aum_from else None},
        "flows": {"from": _flows(from_month), "to": _flows(to_month)},
    }


@router.get("/exceptions")
def exceptions(from_month: str, to_month: str, version: str = "latest") -> dict:
    """The practice team's worklist (Round E 6.2c): rule-cited findings from
    each advisor's latest run on this transition — where the plan expects
    something the data does not show. Every row cites its rule."""
    from app.graph.foundation_store import get_foundation_store

    store = get_insight_store()
    version_id = None if version in ("", "latest") else version
    advisors = store.runs_for_transition(from_month, to_month)
    advisor_names = {sid: (a.get("advisor_name") or "")
                     for sid, a in get_foundation_store()
                     .all_vertices("phx_dm_pce_advisor").items()}
    rows: list[dict] = []
    for sid in sorted({r["advisor_sid"] for r in advisors if r["advisor_sid"] != "all"}):
        run = store.latest_run_for(sid, from_month, to_month, version_id)
        if run is None or run["status"] != "COMPLETE":
            continue
        for finding in store.run_findings(run["run_id"]):
            rule_key = finding.get("rule_key")
            if not rule_key:
                continue  # exceptions are plan-vs-data mismatches — rule-cited only
            rows.append({
                "advisor_sid": sid,
                "advisor_name": advisor_names.get(sid, ""),
                "issue": finding.get("title"),
                "detail": finding.get("summary"),
                "impact_amt": finding.get("impact_amt"),
                "rule_key": rule_key,
                "citation": _rule_citation(rule_key),
                "run_id": run["run_id"],
            })
    rows.sort(key=lambda r: (r["impact_amt"] is None,
                             -(abs(r["impact_amt"]) if r["impact_amt"] is not None else 0)))
    return {"from_month_id": from_month, "to_month_id": to_month,
            "open_count": len(rows),
            "advisor_count": len({r["advisor_sid"] for r in rows}),
            "exceptions": rows}


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

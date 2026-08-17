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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.flags.registry import require_feature
from app.insights.store import get_insight_store
from app.insights.service import get_job_manager
from app.rules.store import get_rule_store

router = APIRouter(prefix="/api/insights", tags=["insights"])


class GenerateRequest(BaseModel):
    advisor: str = Field(..., description='advisor_sid or "all"')
    from_month: str
    to_month: str
    version_id: str | None = None


def _driver_label(finding: dict) -> str:
    from app.rules.drivers import resolve_driver_label, slug_driver_code

    code = finding.get("driver_code") or slug_driver_code(finding.get("driver_tag"))
    return resolve_driver_label(code)


def _serialize_finding(finding: dict) -> dict:
    # Round 3 task 2: the API serves EVERY evidence row (sorted by
    # contribution at storage, footer totals attached) — the UI paginates,
    # the payload is never truncated.
    evidence = finding.get("evidence_rows") or []
    return {
        "finding_id": finding.get("finding_id"),
        "title": finding.get("title"), "summary": finding.get("summary"),
        "impact_amt": finding.get("impact_amt"),
        # Round A1 task 1: driver_code is the stored identity; driver_tag is
        # the DERIVED display label (resolved at read time — a rename reaches
        # every historical finding with no regeneration).
        "driver_code": finding.get("driver_code"),
        "driver_tag": _driver_label(finding),
        # Round A1 task 2: inherited from the producing rule; INFO when no rule
        "severity": finding.get("severity") or "INFO",
        "group_id": finding.get("group_id"),
        # Round 3 review F2 — the display name for the By Product pivot
        "group_name": _group_name(finding.get("group_id")),
        "rule_key": finding.get("rule_key"), "provenance": finding.get("provenance"),
        "confidence": finding.get("confidence"),
        "evidence_columns": finding.get("evidence_columns") or [],
        "evidence_rows": evidence,
        "evidence_total": finding.get("evidence_source_total") or len(evidence),
        # Round 3 task 2 — per-column footer totals so the evidence table
        # reconciles to the finding's headline figure.
        "evidence_totals": finding.get("evidence_totals") or {},
        "evidence_reason": finding.get("evidence_reason"),
        "source_query": finding.get("source_query"),
        "rank_order": finding.get("rank_order"),
    }


def _group_name(group_id: str | None) -> str | None:
    if not group_id:
        return None
    try:
        from app.graph.foundation_store import get_foundation_store

        group = get_foundation_store().all_vertices(
            "phx_dm_pce_product_group").get(str(group_id)) or {}
        return group.get("group_name") or str(group_id)
    except Exception:  # noqa: BLE001 — display sugar, never invented
        return str(group_id)


def _document_name(document_id: str | None) -> str | None:
    """Resolve a rule's document_id to its display name via the knowledge
    catalog (cached per process — the catalog is append-mostly)."""
    if not document_id:
        return None
    global _DOC_NAMES
    if document_id not in _DOC_NAMES:
        try:
            from app.knowledge.knowledge_service import KnowledgeManagementService

            _DOC_NAMES = {d.get("document_id"): d.get("document_name")
                          for d in KnowledgeManagementService().list_documents()}
        except Exception:  # noqa: BLE001 — a name is display sugar, never invented
            return None
    return _DOC_NAMES.get(document_id)


_DOC_NAMES: dict = {}


def _rule_citation(rule_key: str | None) -> dict | None:
    if not rule_key:
        return None
    rule = get_rule_store().get(rule_key)
    if rule is None:
        return None
    citations = rule.get("citations") or []
    citation = dict(citations[0]) if citations else None
    # Round C (docs/rules) task 8, FOUND BY OBSERVATION: extractor citations
    # carry chunk/page/section but no document_name, so the UI rendered
    # "No document citation" on a document-derived rule's finding — the exact
    # chain check 20 exists to prove. The rule's document_id resolves the name.
    if citation is not None and not citation.get("document_name"):
        name = _document_name(rule.get("document_id"))
        if name:
            citation["document_name"] = name
    return {"rule_key": rule_key, "rule_code": rule.get("rule_code"),
            "rule_name": rule.get("rule_name"),
            # Round F 5.1: the driver chip's tooltip is the matched rule's
            # plain-English statement; the frontend falls back to its own
            # definition table only when a finding has no rule.
            "statement": rule.get("statement"),
            "citation": citation}


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
        # Round H 2.3: every limit that bound, loud — name, value, effect.
        "limit_hit": bool(_json.loads(run.get("limits_json") or "[]")),
        "limits_hit": _json.loads(run.get("limits_json") or "[]"),
        "generation": run.get("generation", 1),
        "error": run.get("error"),
    }


@router.post("/generate",
             # Round A2B task 7: OFF means the generation queries do not run
             dependencies=[Depends(require_feature("dashboard.insights"))])
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

    # Round 3 review D2 — AUM is Managed Accounts only wherever it renders;
    # the managed-scoped figure is what the KPI shows, labelled.
    managed = {k for k, a in store.all_vertices("phx_dm_pce_account").items()
               if a.get("is_managed") in (True, "True", "true", 1, "1")}

    def _aum_managed(month_id: str) -> float:
        return round(sum(_f(r.get("end_balance"))
                         for r in store.all_vertices("phx_dm_pce_account_month").values()
                         if str(r.get("advisor_sid")) in cohort
                         and str(r.get("month_id")) == str(month_id)
                         and str(r.get("acct_key")) in managed), 2)

    aum_from, aum_to = _aum(from_month), _aum(to_month)
    aum_change = round(aum_to - aum_from, 2)
    m_from, m_to = _aum_managed(from_month), _aum_managed(to_month)
    m_change = round(m_to - m_from, 2)
    return {
        "from_month_id": from_month, "to_month_id": to_month,
        "advisor_count": len(cohort),
        "credited": totals,  # {from_amt, to_amt, change_amt, change_pct}
        "aum": {"from_amt": aum_from, "to_amt": aum_to, "change_amt": aum_change,
                "change_pct": round(aum_change / aum_from * 100, 2) if aum_from else None},
        "aum_managed": {"from_amt": m_from, "to_amt": m_to, "change_amt": m_change,
                        "change_pct": round(m_change / m_from * 100, 2) if m_from else None},
        "flows": {"from": _flows(from_month), "to": _flows(to_month)},
    }


@router.get("/exceptions/advisors")
def exception_advisors(from_month: str, to_month: str,
                       version: str = "latest") -> dict:
    """Round 3 review batch 1 H4 — the advisors that actually HAVE exceptions
    on this transition (the UI's advisor dropdown lists only these)."""
    from app.graph.foundation_store import get_foundation_store

    store = get_insight_store()
    version_id = None if version in ("", "latest") else version
    names = {sid: (a.get("advisor_name") or "")
             for sid, a in get_foundation_store()
             .all_vertices("phx_dm_pce_advisor").items()}
    counts: dict[str, int] = {}
    runs = store.runs_for_transition(from_month, to_month)
    for sid in sorted({r["advisor_sid"] for r in runs if r["advisor_sid"] != "all"}):
        run = store.latest_run_for(sid, from_month, to_month, version_id)
        if run is None or run["status"] != "COMPLETE":
            continue
        n = len(store.run_findings(run["run_id"]))
        if n:
            counts[sid] = n
    return {"from_month_id": from_month, "to_month_id": to_month,
            "advisors": [{"advisor_sid": sid, "advisor_name": names.get(sid, ""),
                          "exception_count": n}
                         for sid, n in sorted(counts.items())]}


@router.get("/exceptions")
def exceptions(from_month: str, to_month: str, version: str = "latest",
               severity: str | None = None, advisor: str | None = None) -> dict:
    """The practice team's worklist (Round E 6.2c, Round A1 task 2): findings
    from each advisor's latest run on this transition. Rule-cited rows carry
    the rule's severity; rows with no rule are observations at INFO (mockup's
    'Pattern — no rule matched' / 'Observation' rows). Filterable by severity
    (comma-separated levels), sorted Critical → Info then by absolute impact."""
    from app.graph.foundation_store import get_foundation_store
    from app.rules.store import SEVERITIES

    store = get_insight_store()
    version_id = None if version in ("", "latest") else version
    wanted: set[str] | None = None
    if severity:
        wanted = {s.strip().upper() for s in severity.split(",") if s.strip()}
        unknown = wanted - set(SEVERITIES)
        if unknown:
            raise HTTPException(400, f"unknown severity level(s) {sorted(unknown)} — "
                                     f"expected {', '.join(SEVERITIES)}")
    advisors = store.runs_for_transition(from_month, to_month)
    advisor_names = {sid: (a.get("advisor_name") or "")
                     for sid, a in get_foundation_store()
                     .all_vertices("phx_dm_pce_advisor").items()}
    sids = sorted({r["advisor_sid"] for r in advisors if r["advisor_sid"] != "all"})
    # Round 3 review batch 1 H2/H3 — server-side advisor filter, so the UI's
    # default one-advisor view never fetches the whole set.
    if advisor:
        sids = [s for s in sids if s == advisor]
    rows: list[dict] = []
    for sid in sids:
        run = store.latest_run_for(sid, from_month, to_month, version_id)
        if run is None or run["status"] != "COMPLETE":
            continue
        for finding in store.run_findings(run["run_id"]):
            rule_key = finding.get("rule_key")
            level = finding.get("severity") or "INFO"
            if wanted is not None and level not in wanted:
                continue
            rows.append({
                "advisor_sid": sid,
                "advisor_name": advisor_names.get(sid, ""),
                "severity": level,
                "issue": finding.get("title"),
                "detail": finding.get("summary"),
                "impact_amt": finding.get("impact_amt"),
                "rule_key": rule_key,
                "citation": _rule_citation(rule_key),
                "source_kind": "rule" if rule_key else "observation",
                "run_id": run["run_id"],
            })
    rank = {level: i for i, level in enumerate(SEVERITIES)}
    rows.sort(key=lambda r: (rank.get(r["severity"], len(rank)),
                             r["impact_amt"] is None,
                             -(abs(r["impact_amt"]) if r["impact_amt"] is not None else 0)))
    return {"from_month_id": from_month, "to_month_id": to_month,
            "open_count": len(rows),
            "advisor_count": len({r["advisor_sid"] for r in rows}),
            "exceptions": rows}


# Round A1 task 2 — spec path: GET /api/exceptions?from=&to=&severity=
alias_router = APIRouter(tags=["insights"])


@alias_router.get("/api/exceptions")
def exceptions_alias(from_: str = Query(alias="from"), to: str = Query(...),
                     severity: str | None = None, version: str = "latest") -> dict:
    return exceptions(from_month=from_, to_month=to, version=version,
                      severity=severity)


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


@router.get("/{advisor}/{from_month}/{to_month}",
            # Round A2B task 7: stored-run reads are gated with generation
            dependencies=[Depends(require_feature("dashboard.insights"))])
def get_insights(advisor: str, from_month: str, to_month: str,
                 version: str = "latest") -> dict:
    store = get_insight_store()
    version_id = None if version in ("", "latest") else version
    run = store.latest_run_for(advisor, from_month, to_month, version_id)
    if run is None:
        raise HTTPException(404, f"no insight run for {advisor} {from_month}->{to_month}"
                                 + (f" at version {version}" if version_id else ""))
    return _serialize_run(run, store.run_findings(run["run_id"]))

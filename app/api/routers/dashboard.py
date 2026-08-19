"""B1 dashboard endpoints.

Every figure is a graph query result served through the tiered graph client —
the router only shapes/unwraps; it computes nothing. The mock tier's Python
equivalents live in ``app/graph/queries/pce_dashboard.py`` (imported below so
the ``@mock_query`` registrations run regardless of which module loads first).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import app.graph.queries.pce_dashboard  # noqa: F401 — registers the mock-tier query impls
from app.graph.client import get_graph_client
from app.shared.logging import get_logger

_log = get_logger("app.api.dashboard")

router = APIRouter(prefix="/api", tags=["dashboard"])

_VALID_CLASSES = {"all", "RECURRING", "NON_RECURRING"}


def _run(query_name: str, params: dict) -> dict:
    """Run a dashboard query through run_catalog_query (Round 10 task 4 — the
    guarded path; the pce_dashboard_* entries are internal local_compute) and
    unwrap the single shaped result row.

    An empty ``rows`` list here is a TRANSPORT/CONTRACT failure, never a data
    zero: every dashboard impl returns exactly one shaped row even over an
    empty dataset (e.g. {"months": []}), so a legitimate zero arrives INSIDE
    that row — the 502 says so explicitly."""
    from app.graph.queries.catalog import run_catalog_query

    try:
        result = run_catalog_query(query_name, params, allow_internal=True)
    except ValueError as exc:  # bad request parameters surfaced by the query
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = result.get("rows") or []
    if not rows:
        raise HTTPException(
            status_code=502,
            detail=f"graph query '{query_name}' returned no result envelope — "
                   f"a transport/contract failure, NOT an empty dataset (an "
                   f"empty dataset arrives as a shaped row, e.g. months: [])")
    return rows[0]


@router.get("/advisors")
def get_advisors() -> dict:
    return _run("pce_dashboard_advisors", {})


@router.get("/months")
def get_months(advisor: str = Query("all")) -> dict:
    return _run("pce_dashboard_months", {"advisor": advisor})


@router.get("/transitions")
def get_transitions(advisor: str = Query("all")) -> dict:
    return _run("pce_dashboard_transitions", {"advisor": advisor})


@router.get("/product-contribution")
def get_product_contribution(
    from_month: str = Query(..., alias="from"),
    to_month: str = Query(..., alias="to"),
    advisor: str = Query("all"),
    class_id: str = Query("all", alias="class"),
) -> dict:
    if class_id not in _VALID_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown class '{class_id}' (expected all|RECURRING|NON_RECURRING)",
        )
    return _run(
        "pce_dashboard_product_contribution",
        {"from": from_month, "to": to_month, "advisor": advisor, "class": class_id},
    )


# ---------------------------------------------------------------- Round A1 task 3.2
# The expanded table and chart. All figures come from catalog queries
# (app/graph/queries/catalog.py — product_month_metrics, product_transition_table,
# month_aum, advisor_count_by_product); the router composes and shapes only.
# Metric definitions are served from app/shared/glossary.METRIC_DEFINITIONS —
# the ONE source, never restated here.

from app.graph.queries.catalog import (  # noqa: E402
    PRODUCT_VIEWS,
    TOTAL_ROW_ID,
    CatalogError,
    run_catalog_query,
)
from app.shared.glossary import METRIC_DEFINITIONS  # noqa: E402


def _catalog(query_name: str, params: dict) -> list[dict]:
    try:
        return run_catalog_query(query_name, params)["rows"]
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _check_view(view: str) -> str:
    if view not in PRODUCT_VIEWS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown view '{view}' (expected {'|'.join(PRODUCT_VIEWS)})")
    return view


@router.get("/dashboard/lifecycle")
def get_dashboard_lifecycle(
    from_month: str = Query(..., alias="from"),
    to_month: str = Query(..., alias="to"),
    scope: str = Query("all", description="advisor_sid | group_id | 'all'"),
) -> dict:
    """Round 3 review D8 — New / Lost / Retained counts scoped to a drill-down
    level (a product group's counts at product level, an advisor's at advisor
    level, the firm's at 'all'). Straight from account_lifecycle_counts (rule
    outcomes — deterministic, exclusion-chain honest; skipped rules are named
    in notes, never a silent zero)."""
    rows = _catalog("account_lifecycle_counts",
                    {"from_month": from_month, "to_month": to_month,
                     "scope": scope})
    return {"from": from_month, "to": to_month, **rows[0]}


@router.get("/dashboard/definitions")
def get_dashboard_definitions() -> dict:
    """The dashboard's metric definitions — the same METRIC_DEFINITIONS the
    glossary serves (one source, never restated)."""
    return {"definitions": METRIC_DEFINITIONS}


@router.get("/dashboard/table")
def get_dashboard_table(
    from_month: str = Query(..., alias="from"),
    to_month: str = Query(..., alias="to"),
    view: str = Query("all"),
) -> dict:
    _check_view(view)
    rows = _catalog("product_transition_table",
                    {"from_month": from_month, "to_month": to_month,
                     "product_view": view})
    total = next(r for r in rows if r["group_id"] == TOTAL_ROW_ID)
    body = [r for r in rows if r["group_id"] != TOTAL_ROW_ID]
    for row in body:  # the mockup's per-row Advisors column
        row["advisor_count"] = _catalog(
            "advisor_count_by_product",
            {"month_id": to_month, "group_id": row["group_id"]})[0]["advisor_count"]
    total["advisor_count"] = _catalog(
        "advisor_count_by_product",
        {"month_id": to_month, "group_id": "all"})[0]["advisor_count"]
    return {"from": from_month, "to": to_month, "view": view,
            "rows": body, "total": total, "definitions": METRIC_DEFINITIONS}


@router.get("/dashboard/chart")
def get_dashboard_chart(view: str = Query("all")) -> dict:
    _check_view(view)
    month_ids = [m["month_id"]
                 for m in _run("pce_dashboard_months", {"advisor": "all"})["months"]]
    months = []
    for month_id in month_ids:
        # split rows carry class_id, so one call yields both class amounts;
        # a filtered view simply reads its own class only.
        rows = _catalog("product_month_metrics",
                        {"month_id": month_id, "product_view": view})
        recurring = round(sum(r["credited_amt"] for r in rows
                              if r["class_id"] == "RECURRING"), 2)
        non_recurring = round(sum(r["credited_amt"] for r in rows
                                  if r["class_id"] == "NON_RECURRING"), 2)
        aum = _catalog("month_aum",
                       {"month_id": month_id, "product_view": view})[0]["aum"]
        months.append({
            "month_id": month_id,
            "credited_amt": round(recurring + non_recurring, 2),
            "recurring_amt": recurring,
            "non_recurring_amt": non_recurring,
            "aum": aum,
        })
    transitions = []
    for prev, curr in zip(months, months[1:]):
        change = round(curr["credited_amt"] - prev["credited_amt"], 2)
        transitions.append({
            "from": prev["month_id"], "to": curr["month_id"],
            "change_amt": change,
            # existing decision: change_pct is null when the from amount is 0
            "change_pct": (round(change / prev["credited_amt"] * 100, 2)
                           if prev["credited_amt"] else None),
            "direction": "up" if change >= 0 else "down",
        })
    return {"view": view, "months": months, "transitions": transitions}

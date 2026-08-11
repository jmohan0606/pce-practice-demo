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
    """Run a catalog query and unwrap its single shaped result row."""
    try:
        result = get_graph_client().run_query(query_name, params)
    except ValueError as exc:  # bad request parameters surfaced by the query
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    results = result.get("results") or []
    if not results:
        raise HTTPException(status_code=502, detail=f"graph query '{query_name}' returned no results")
    return results[0]


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

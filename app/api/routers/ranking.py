"""Round A1 task 5 — top/bottom advisor ranking API. Owned by Subagent B.

Lives in its own router (not dashboard.py) so Subagents A and B never edit the
same file; the route path still sits under /api/dashboard per the spec.

GET /api/dashboard/product/{group_id}/ranking?from=&to=[&limit=]

Top N and bottom N cohort advisors by CHANGE AMOUNT for the product group.
``dominant_driver_code`` comes deterministically from rule evaluation outcomes
and is null — never guessed — when no rule outcome exists for the advisor
(the UI shows "AI Insights not generated yet"). ``advisor_name`` is returned
separately from the SID; a blank name stays blank.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.graph.queries.catalog import CatalogError
from app.graph.queries.noncredited import run_noncredited_query

router = APIRouter(prefix="/api/dashboard", tags=["ranking"])


@router.get("/product/{group_id}/ranking")
def product_ranking(group_id: str,
                    from_month: str = Query(..., alias="from"),
                    to_month: str = Query(..., alias="to"),
                    limit: int = Query(10, ge=1, le=50)) -> dict:
    try:
        result = run_noncredited_query("product_advisor_ranking", {
            "from_month": from_month, "to_month": to_month,
            "group_id": group_id, "limit": limit,
        })
    except CatalogError as exc:
        raise HTTPException(404 if "unknown" in str(exc).lower() else 400,
                            str(exc)) from exc
    rows = result["rows"]  # ordered by change_amt desc; each row tagged side
    top = [r for r in rows if r["side"] in ("top", "both")][:limit]
    bottom = sorted([r for r in rows if r["side"] in ("bottom", "both")],
                    key=lambda r: (r["change_amt"], r["advisor_sid"]))[:limit]
    return {
        "group_id": group_id, "from": from_month, "to": to_month,
        "ranked_by": "change_amt", "limit": limit,
        "advisor_count": rows[0]["group_advisor_count"] if rows else 0,
        "total_change_amt": rows[0]["group_total_change_amt"] if rows else 0.0,
        "top": top, "bottom": bottom,
    }

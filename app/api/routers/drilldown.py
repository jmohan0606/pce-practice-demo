"""Round G task 3 — the drill-down API (ROUND_G_SPEC 3.4 / ROUND_G_INTERFACE §3-4).

GET  /api/drilldown/product/{group_id}?from=&to=
GET  /api/drilldown/product/{group_id}/advisors?from=&to=
GET  /api/drilldown/product/{group_id}/advisor/{sid}/accounts?from=&to=
GET  /api/drilldown/product/{group_id}/advisor/{sid}/account/{acct}?from=&to=
GET  /api/drilldown/product/{group_id}/advisor/{sid}/account/{acct}/txns?from=&to=
POST /api/drilldown/generate   {scope, scope_key, from, to}

GET always returns the deterministic parts; ``generated`` gates only the AI
parts, and ``generated: false`` carries an honest cost/time estimate. The
transaction level is a deterministic listing — no LLM, no run, ever. The
account GET (without /txns) is an ADDITION beyond the contract's five so the
stored product_account run is reachable by GET — flagged in the subagent
report for the main thread's review.

Findings serialize exactly as /api/insights runs do (same helpers)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.routers.insights import _rule_citation, _serialize_finding
from app.graph.queries.catalog import CatalogError
from app.insights.drilldown import (DRILLDOWN_SCOPES, DrilldownError,
                                    generate_drilldown, get_drilldown,
                                    make_scope_key, txn_level)

router = APIRouter(prefix="/api/drilldown", tags=["drilldown"])


class GenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope: str = Field(..., description="product | product_advisor | product_account")
    scope_key: str = Field(..., description="'~'-joined scope key parts")
    from_month: str = Field(..., alias="from")
    to_month: str = Field(..., alias="to")


def _serialize_level(payload: dict) -> dict:
    """The contract §4 shape; findings serialized as /api/insights serves them."""
    if "findings" in payload:
        serialized = []
        for f in payload["findings"]:
            row = _serialize_finding(f)
            row["rule_citation"] = _rule_citation(row["rule_key"])
            serialized.append(row)
        payload["findings"] = serialized
    return payload


def _get_level(scope: str, scope_key: str, from_month: str, to_month: str) -> dict:
    try:
        return _serialize_level(get_drilldown(scope, scope_key, from_month, to_month))
    except (DrilldownError, CatalogError) as exc:
        raise HTTPException(404 if "unknown" in str(exc).lower()
                            or "no " in str(exc).lower() else 400,
                            str(exc)) from exc


@router.get("/product/{group_id}")
def product_level(group_id: str, from_month: str = Query(..., alias="from"),
                  to_month: str = Query(..., alias="to")) -> dict:
    return _get_level("product", make_scope_key(group_id), from_month, to_month)


@router.get("/product/{group_id}/advisors")
def product_advisors_level(group_id: str,
                           from_month: str = Query(..., alias="from"),
                           to_month: str = Query(..., alias="to")) -> dict:
    """The advisors listing view of the product level — the SAME product-scope
    run/payload (its contribution rows ARE the advisors); the panel's advisor
    breadcrumb stop renders from these contributions."""
    return _get_level("product", make_scope_key(group_id), from_month, to_month)


@router.get("/product/{group_id}/advisor/{sid}/accounts")
def product_advisor_level(group_id: str, sid: str,
                          from_month: str = Query(..., alias="from"),
                          to_month: str = Query(..., alias="to")) -> dict:
    return _get_level("product_advisor", make_scope_key(group_id, sid),
                      from_month, to_month)


@router.get("/product/{group_id}/advisor/{sid}/account/{acct}")
def product_account_level(group_id: str, sid: str, acct: str,
                          from_month: str = Query(..., alias="from"),
                          to_month: str = Query(..., alias="to")) -> dict:
    return _get_level("product_account", make_scope_key(group_id, sid, acct),
                      from_month, to_month)


@router.get("/product/{group_id}/advisor/{sid}/account/{acct}/txns")
def product_txns_level(group_id: str, sid: str, acct: str,
                       from_month: str = Query(..., alias="from"),
                       to_month: str = Query(..., alias="to")) -> dict:
    """Transaction level: deterministic listing, NO LLM call ever."""
    try:
        return txn_level(group_id, sid, acct, from_month, to_month)
    except (DrilldownError, CatalogError) as exc:
        raise HTTPException(404 if "unknown" in str(exc).lower() else 400,
                            str(exc)) from exc


@router.post("/generate")
def generate(body: GenerateRequest) -> dict:
    if body.scope not in DRILLDOWN_SCOPES:
        raise HTTPException(
            400, f"unknown scope '{body.scope}' — expected one of "
                 f"{', '.join(DRILLDOWN_SCOPES)} (the transaction level is "
                 f"deterministic and never generated)")
    try:
        return _serialize_level(generate_drilldown(
            body.scope, body.scope_key, body.from_month, body.to_month))
    except (DrilldownError, CatalogError) as exc:
        raise HTTPException(400, str(exc)) from exc

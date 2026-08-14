"""Round A1 task 1 — drivers and glossary.

GET /api/drivers   every known driver: driver_code, driver_label,
                   driver_definition, rule_key, source (document citation or
                   TECH_TEAM_WRITTEN)
GET /api/glossary  every term the UI explains in a tooltip, keyed by stable
                   term code (metric.* / driver.* / severity.* / provenance.* /
                   noncredited.*) — ONE server-side source, so the same term is
                   never explained three different ways on three screens.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.rules.seed import ensure_v0_seed

router = APIRouter(prefix="/api", tags=["glossary"],
                   dependencies=[Depends(ensure_v0_seed)])


@router.get("/drivers")
def drivers() -> dict:
    from app.rules.drivers import list_drivers

    rows = list_drivers()
    return {"drivers": rows, "driver_count": len(rows)}


@router.get("/glossary")
def glossary() -> dict:
    from app.shared.glossary import build_glossary

    return build_glossary()

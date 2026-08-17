"""Round 3 task 3.2 — the three exception altitudes over the rate model.

| Altitude | Endpoint | Answers |
|---|---|---|
| firm      | GET /api/exceptions/firm            | How big is each problem? (one row per RULE) |
| per rule  | GET /api/exceptions/rule/{rule_key} | Which advisors are out of line? (ranked by RATE) |
| advisor   | GET /api/exceptions/advisor/{sid}   | Am I out of line? (my rate vs the cohort median) |

The rate model itself lives in app/insights/exceptions.py. The per-rule
configuration (the eight Round-1 fields) is edited through
PATCH /api/rules/{rule_key}/exception-config.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.flags.registry import require_feature
from app.insights.exceptions import (
    compute_advisor_exceptions,
    compute_firm_exceptions,
    compute_rule_exceptions,
    exception_rules,
)

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])


@router.get("/firm")
def firm(month: str, version: str = "latest") -> dict:
    require_feature("dashboard.exceptions")
    version_id = None if version in ("", "latest") else version
    return compute_firm_exceptions(month, version_id)


@router.get("/rule/{rule_key}")
def rule(rule_key: str, month: str, version: str = "latest") -> dict:
    require_feature("dashboard.exceptions")
    version_id = None if version in ("", "latest") else version
    match = [r for r in exception_rules(version_id) if r.get("rule_key") == rule_key]
    if not match:
        raise HTTPException(
            404, f"rule {rule_key!r} is not an exception-enabled rule of the "
                 f"served version")
    return compute_rule_exceptions(match[0], month, version_id=version_id)


@router.get("/advisor/{advisor_sid}")
def advisor(advisor_sid: str, month: str, version: str = "latest") -> dict:
    require_feature("dashboard.exceptions")
    version_id = None if version in ("", "latest") else version
    return compute_advisor_exceptions(advisor_sid, month, version_id)

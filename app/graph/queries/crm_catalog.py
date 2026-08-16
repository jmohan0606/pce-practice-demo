"""Round F2 task 3 — CRM opportunity catalog queries (Subagent A's module).

catalog.py imports this at the end of its own module load and merges
EXTRA_CATALOG into CATALOG; @mock_query implementations register on import.
GSQL twins live under docs/tigergraph/queries/.

HONESTY CONSTRAINTS (spec §2):
- No Won/Lost status exists in the source and none is derived here.
- `amount` (forecast pipeline value) and `actual_assets` (assets that landed)
  are NEVER summed together — separate columns everywhere.
- `ai_read` is descriptive interpretation text. Detail-row queries RETURN it
  (with confidence + evidence, so the UI/chat can show it beside the verbatim
  comment) but NO aggregate touches it: it never filters, sums, sorts or
  feeds a figure.
- Invalid advisor references (advisor_valid=false) stay queryable; aggregates
  count them per scope so the data-quality line has a source.
"""
from __future__ import annotations

from app.graph.client import mock_query
from app.graph.foundation_store import FoundationGraphStore
from typing import Any

from app.shared.crm import STAGE_GROUP_ORDER

# NOTE: nothing is imported from catalog.py at module level — catalog.py
# imports THIS module at the end of its own load, so a top-level import back
# into catalog blows up whenever this module is imported first (proven; same
# fix as nnm_catalog.py). CatalogError is raised lazily; _p/_num/ADVISOR
# replicate catalog's shapes verbatim.


def _p(name: str, ptype: str, required: bool = True, default: Any = None) -> dict:
    return {"name": name, "type": ptype, "required": required, "default": default}


ADVISOR = _p("advisor", "advisor_sid | 'all'")


def _num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class _LazyCatalogError:
    """Raise catalog.CatalogError without importing it at module level."""

    def __call__(self, msg: str) -> Exception:
        from app.graph.queries.catalog import CatalogError

        return CatalogError(msg)


CatalogError = _LazyCatalogError()

V_OPP = "phx_dm_pce_opportunity"

_GROUP_RANK = {g: i for i, g in enumerate(STAGE_GROUP_ORDER)}


def _advisor_scope(store: FoundationGraphStore, advisor: str) -> set[str]:
    from app.graph.queries.catalog import _advisor_scope as base_scope

    return base_scope(store, advisor)


def _opps(store: FoundationGraphStore) -> list[dict]:
    return sorted(store.all_vertices(V_OPP).values(),
                  key=lambda r: str(r.get("opportunity_id")))


def _detail_row(r: dict) -> dict:
    """One opportunity with the three-provenance columns: source stage, the
    verbatim comment, and the labelled AI interpretation beside it."""
    return {
        "opportunity_id": str(r.get("opportunity_id")),
        "eci_id": str(r.get("eci_id") or ""),
        "advisor_sid": str(r.get("advisor_sid") or ""),
        "advisor_valid": r.get("advisor_valid") in (True, "true"),
        "account_record_type": str(r.get("account_record_type") or ""),
        "stage_name": str(r.get("stage_name") or ""),
        "stage_group": str(r.get("stage_group") or ""),
        "amount": round(_num(r.get("amount")), 2),
        "actual_assets": round(_num(r.get("actual_assets")), 2),
        "days_to_close": int(_num(r.get("days_to_close"))),
        "is_stalled": r.get("is_stalled") in (True, "true"),
        "date_of_last_contact": str(r.get("date_of_last_contact") or ""),
        "comments": str(r.get("comments") or ""),
        "ai_read": str(r.get("ai_read") or ""),
        "ai_read_confidence": _num(r.get("ai_read_confidence")) or None,
        "ai_read_evidence": str(r.get("ai_read_evidence") or ""),
        "data_source": str(r.get("data_source") or "CRM"),
    }


@mock_query("advisor_pipeline")
def advisor_pipeline(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    out: dict[tuple, dict] = {}
    for r in _opps(store):
        sid = str(r.get("advisor_sid"))
        if sid not in scope:
            continue
        key = (sid, str(r.get("stage_group") or ""))
        row = out.setdefault(key, {
            "advisor_sid": sid, "stage_group": key[1],
            "opportunity_count": 0, "forecast_amount": 0.0,
            "actual_assets": 0.0, "stalled_count": 0, "invalid_advisor_count": 0})
        row["opportunity_count"] += 1
        row["forecast_amount"] = round(row["forecast_amount"] + _num(r.get("amount")), 2)
        row["actual_assets"] = round(row["actual_assets"] + _num(r.get("actual_assets")), 2)
        if r.get("is_stalled") in (True, "true"):
            row["stalled_count"] += 1
        if r.get("advisor_valid") in (False, "false"):
            row["invalid_advisor_count"] += 1
    return sorted(out.values(),
                  key=lambda r: (r["advisor_sid"], _GROUP_RANK.get(r["stage_group"], 99)))


@mock_query("advisor_opportunity_detail")
def advisor_opportunity_detail(store: FoundationGraphStore, params: dict) -> list[dict]:
    """Every opportunity row for one advisor (or the cohort), stalled first
    then by landed assets — sorted on SOURCE data only, never on ai_read."""
    scope = _advisor_scope(store, params["advisor"])
    rows = [_detail_row(r) for r in _opps(store)
            if str(r.get("advisor_sid")) in scope]
    return sorted(rows, key=lambda r: (not r["is_stalled"], -r["actual_assets"],
                                       r["opportunity_id"]))


@mock_query("household_opportunities")
def household_opportunities(store: FoundationGraphStore, params: dict) -> list[dict]:
    eci_id = str(params["eci_id"])
    rows = [_detail_row(r) for r in _opps(store) if str(r.get("eci_id")) == eci_id]
    if not rows:
        households = store.all_vertices("phx_dm_pce_household")
        if eci_id not in households:
            raise CatalogError(f"unknown household '{eci_id}'")
    return sorted(rows, key=lambda r: (not r["is_stalled"], -r["actual_assets"]))


@mock_query("pipeline_by_stage")
def pipeline_by_stage(store: FoundationGraphStore, params: dict) -> list[dict]:
    out: dict[str, dict] = {}
    for r in _opps(store):
        stage = str(r.get("stage_name") or "")
        row = out.setdefault(stage, {
            "stage_name": stage, "stage_group": str(r.get("stage_group") or ""),
            "opportunity_count": 0, "forecast_amount": 0.0, "actual_assets": 0.0,
            "stalled_count": 0})
        row["opportunity_count"] += 1
        row["forecast_amount"] = round(row["forecast_amount"] + _num(r.get("amount")), 2)
        row["actual_assets"] = round(row["actual_assets"] + _num(r.get("actual_assets")), 2)
        if r.get("is_stalled") in (True, "true"):
            row["stalled_count"] += 1
    return sorted(out.values(),
                  key=lambda r: (_GROUP_RANK.get(r["stage_group"], 99), r["stage_name"]))


@mock_query("stalled_opportunities")
def stalled_opportunities(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    rows = []
    for r in _opps(store):
        if str(r.get("advisor_sid")) not in scope:
            continue
        days = int(_num(r.get("days_to_close")))
        if days >= 0:
            continue  # stalled = past the anticipated close date
        d = _detail_row(r)
        d["days_past_due"] = -days
        rows.append(d)
    return sorted(rows, key=lambda r: (-r["days_past_due"], r["opportunity_id"]))


EXTRA_CATALOG: dict[str, dict] = {
    "advisor_pipeline": {
        "description": "CRM pipeline per advisor grouped by stage group (EARLY|MID|LATE|CLOSING): "
                       "opportunity count, forecast amount (Salesforce Amount — forecast pipeline "
                       "value), actual assets (landed — NEVER summed with forecast), stalled count "
                       "(past anticipated close), invalid-advisor count. Source: real CRM extract; "
                       "no Won/Lost stage exists in the source.",
        "params": [ADVISOR],
        "returns": ["advisor_sid", "stage_group", "opportunity_count", "forecast_amount",
                    "actual_assets", "stalled_count", "invalid_advisor_count"],
    },
    "advisor_opportunity_detail": {
        "description": "Every CRM opportunity row for an advisor (or the cohort with "
                       "advisor='all'): stage, amounts, days to close, verbatim comment and the "
                       "labelled AI reading beside it (descriptive only — never drives a figure). "
                       "Stalled rows sort first.",
        "params": [ADVISOR],
        "returns": ["opportunity_id", "eci_id", "advisor_sid", "advisor_valid",
                    "account_record_type", "stage_name", "stage_group", "amount",
                    "actual_assets", "days_to_close", "is_stalled", "date_of_last_contact",
                    "comments", "ai_read", "ai_read_confidence", "ai_read_evidence",
                    "data_source"],
    },
    "household_opportunities": {
        "description": "One household's CRM opportunities with stage, forecast amount, actual "
                       "assets, days to close, the verbatim comment and the labelled AI reading "
                       "(descriptive only — never drives a figure).",
        "params": [_p("eci_id", "string")],
        "returns": ["opportunity_id", "eci_id", "advisor_sid", "advisor_valid",
                    "account_record_type", "stage_name", "stage_group", "amount",
                    "actual_assets", "days_to_close", "is_stalled", "date_of_last_contact",
                    "comments", "ai_read", "ai_read_confidence", "ai_read_evidence",
                    "data_source"],
    },
    "pipeline_by_stage": {
        "description": "Practice-level CRM pipeline by source stage name (the 15 Salesforce "
                       "stages): count, forecast amount, actual assets, stalled count. No "
                       "Won/Lost stage exists in the source and none is derived.",
        "params": [],
        "returns": ["stage_name", "stage_group", "opportunity_count", "forecast_amount",
                    "actual_assets", "stalled_count"],
    },
    "stalled_opportunities": {
        "description": "Opportunities past their anticipated close date (days_to_close < 0) — "
                       "days past due, last contact date, amounts, verbatim comment and AI "
                       "reading. The actionable straight-from-data finding.",
        "params": [ADVISOR],
        "returns": ["opportunity_id", "eci_id", "advisor_sid", "advisor_valid",
                    "account_record_type", "stage_name", "stage_group", "amount",
                    "actual_assets", "days_to_close", "days_past_due", "is_stalled",
                    "date_of_last_contact", "comments", "ai_read", "ai_read_confidence",
                    "ai_read_evidence", "data_source"],
    },
}

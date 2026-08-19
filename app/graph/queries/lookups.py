"""Round 9 task 9 — shared tiered-client lookups for the converted read sites.

Every module outside app/graph/ used to read the foundation store directly for
month lists, advisor directories, bulk managed flags and similar small
lookups — reads that silently served MOCK rows in real mode (the evaluator
bug, found in the client environment). These helpers are the ONE replacement:
each goes through ``run_catalog_query`` — the guarded, tiered path — using
either a named catalog query or the internal ``rule_evaluation_rows`` generic
vertex fetch (the spec's preferred alternative to minting new query names,
since every new name needs a GSQL twin installed in the client environment).

Row shape note: ``rule_evaluation_rows`` rows carry ``__vertex_id`` (the
primary key) plus the projected attributes, exactly matching the old
``store.all_vertices(...)`` items keyed by vertex id.
"""
from __future__ import annotations

from typing import Any

V_ADVISOR = "phx_dm_pce_advisor"
V_MONTH = "phx_dm_pce_month"
V_ACCOUNT = "phx_dm_pce_account"
V_AM = "phx_dm_pce_account_month"
V_TXN = "phx_dm_pce_revenue_transaction"
V_FLOW = "phx_dm_pce_advisor_flow_month"
V_TEAM = "phx_dm_pce_team_agreement"
V_PRODUCT = "phx_dm_pce_product"


def fetch_vertex_rows(vertex_type: str, *, month: str | None = None,
                      advisor_sid: str | None = None, key: str | None = None,
                      columns: str | None = None) -> list[dict]:
    """Raw rows of one vertex type through the tiered client (the internal
    ``rule_evaluation_rows`` entry): month/advisor filters run server-side,
    ``columns`` (comma-separated) projects the result. Each row carries
    ``__vertex_id``."""
    from app.graph.queries.catalog import run_catalog_query

    params: dict[str, Any] = {"vertex_type": vertex_type}
    if month not in (None, ""):
        params["month"] = str(month)
    if advisor_sid not in (None, ""):
        params["advisor_sid"] = str(advisor_sid)
    if key not in (None, ""):
        params["key_id"] = str(key)
    if columns:
        params["columns"] = columns
    return run_catalog_query("rule_evaluation_rows", params,
                             allow_internal=True)["rows"]


def month_ids() -> list[str]:
    """Sorted month ids — the old ``sorted(store.all_vertices(month))``."""
    return sorted(r["__vertex_id"]
                  for r in fetch_vertex_rows(V_MONTH, columns="month_id"))


def month_row(month_id: str) -> dict | None:
    """One month's attributes, or None when unknown."""
    rows = fetch_vertex_rows(V_MONTH, key=str(month_id))
    return rows[0] if rows else None


def advisor_rows(columns: str | None = None) -> dict[str, dict]:
    """Every advisor (non-cohort and synthetic included), keyed by SID — the
    old ``store.all_vertices(advisor)``."""
    return {r["__vertex_id"]: r
            for r in fetch_vertex_rows(V_ADVISOR, columns=columns)}


def cohort_sids() -> list[str]:
    """Sorted cohort SIDs (in_cohort is true)."""
    return sorted(sid for sid, a in advisor_rows(columns="in_cohort").items()
                  if a.get("in_cohort") is True)


def advisor_names() -> dict[str, str]:
    """SID -> advisor_name ('' preserved — a blank name stays blank)."""
    return {sid: a.get("advisor_name") or ""
            for sid, a in advisor_rows(columns="advisor_name").items()}


def account_managed_map() -> dict[str, bool]:
    """acct_key -> is_managed over every account (the audit's
    account_managed_flags query)."""
    from app.graph.queries.catalog import run_catalog_query

    return {str(r["acct_key"]): bool(r["is_managed"])
            for r in run_catalog_query("account_managed_flags", {})["rows"]}


def product_group_name(group_id: str) -> str:
    """Group name, falling back to the raw id — never invented."""
    from app.graph.queries.catalog import run_catalog_query

    rows = run_catalog_query("product_group_master",
                             {"group_id": str(group_id)})["rows"]
    return (rows[0].get("group_name") or str(group_id)) if rows else str(group_id)

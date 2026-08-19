"""Export providers — one per section, each returning the normalized table
payload from app/export/payload.py. The registry at the bottom is what the
router and renderers dispatch on; a new section is one new provider here.

Data-source note (Round A1 parallel build): concurrent subagents are extending
app/graph/queries/catalog.py and building noncredited.py — those modules are
deliberately NOT imported here. dashboard_table reads the EXISTING Round B
dashboard query; noncredited reads the transaction vertices directly.
"""
from __future__ import annotations

from typing import Any, Callable

from app.export.payload import col, make_payload
from app.shared.glossary import METRIC_DEFINITIONS

SECTIONS = ("dashboard_table", "noncredited", "exceptions", "insights")

_VIEW_TO_CLASS = {"all": "all", "split": "all",
                  "recurring": "RECURRING", "non_recurring": "NON_RECURRING"}
_VIEW_LABEL = {"all": "All products", "split": "Recurring / Non-recurring split",
               "recurring": "Recurring only", "non_recurring": "Non-recurring only"}


class ExportParamError(ValueError):
    """Bad request parameters for an export (surfaced as HTTP 400)."""


def _require(params: dict, *names: str) -> list[str]:
    values = []
    for name in names:
        value = str(params.get(name) or "").strip()
        if not value:
            raise ExportParamError(f"missing required param '{name}'")
        values.append(value)
    return values


def _transition_text(from_month: str, to_month: str, view: str | None = None) -> str:
    text = f"Transition {from_month} → {to_month}"
    if view:
        text += f" · View: {_VIEW_LABEL.get(view, view)}"
    return text


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# dashboard_table
# ---------------------------------------------------------------------------

def _dashboard_table_source(from_month: str, to_month: str, view: str) -> list[dict]:
    """Round A1 main-thread repoint (the designed one-function swap): the
    export now reads Task 3's ``product_transition_table`` catalog query — the
    same rows the on-screen expanded table binds to, including accounts/trades
    and per-view share_pct. The ``__TOTAL__`` row rides last."""
    from app.graph.queries.catalog import CatalogError, run_catalog_query

    try:
        return run_catalog_query("product_transition_table", {
            "from_month": from_month, "to_month": to_month,
            "product_view": "non_recurring" if view == "nrec" else view})["rows"]
    except CatalogError as exc:
        raise ExportParamError(str(exc)) from exc


def provide_dashboard_table(params: dict) -> dict:
    from_month, to_month = _require(params, "from", "to")
    view = str(params.get("view") or "all")
    if view not in _VIEW_TO_CLASS:
        raise ExportParamError(
            f"unknown view '{view}' (expected all|split|recurring|non_recurring)")
    advisor = str(params.get("advisor") or "all")
    if advisor not in ("", "all"):
        raise ExportParamError(
            "the dashboard table is firm-level — it has no advisor filter on "
            "screen, so an advisor-scoped export of it would not reproduce the "
            "screen; use section=insights for advisor-scoped output")
    data = _dashboard_table_source(from_month, to_month, view)

    columns = [
        col("class_id", "Class"),
        col("group_name", "Product"),
        col("from_account_count", f"{from_month} Accts", "int"),
        col("from_trade_count", f"{from_month} Trades", "int"),
        col("from_amt", f"{from_month} Revenue", "money"),
        col("to_account_count", f"{to_month} Accts", "int"),
        col("to_trade_count", f"{to_month} Trades", "int"),
        col("to_amt", f"{to_month} Revenue", "money"),
        col("account_delta", "\u0394 Accts", "int", signed=True),
        col("trade_delta", "\u0394 Trades", "int", signed=True),
        col("change_amt", "\u0394 Revenue", "money", signed=True),
        col("change_pct", "Change %", "pct", signed=True),
        col("share_pct", "Share %", "pct"),
    ]
    keys = [c["key"] for c in columns]
    rows: list[dict] = []
    totals = None
    for row in data:
        flat = {k: row.get(k) for k in keys}
        flat["group_name"] = ((row.get("display_prefix") or "")
                              + (row.get("group_name") or ""))
        if row.get("group_id") == "__TOTAL__":
            flat["group_name"] = "Total (all product types)"
            totals = flat
        else:
            rows.append(flat)

    return make_payload(
        "dashboard_table", params,
        title="What Is Driving the Change",
        subtitle=_transition_text(from_month, to_month, view),
        columns=columns, rows=rows, totals=totals if rows else None,
        footnotes=[f"{name}: {definition}"
                   for name, definition in METRIC_DEFINITIONS.items()],
        filename_stem=f"dashboard_table_{from_month}-{to_month}_{view}")


# ---------------------------------------------------------------------------
# noncredited
# ---------------------------------------------------------------------------

def provide_noncredited(params: dict) -> dict:
    from app.graph.queries import lookups
    from app.shared.reason_codes import cause_for_code

    month = str(params.get("month") or params.get("to") or "").strip()
    if not month:
        raise ExportParamError("missing required param 'month' (or 'to')")
    if lookups.month_row(month) is None:
        raise ExportParamError(f"unknown month '{month}'")

    grouped: dict[str, dict] = {}
    for txn in lookups.fetch_vertex_rows(
            "phx_dm_pce_revenue_transaction", month=month,
            columns="reason_cd,acct_key,advisor_sid,non_credited_amt,pre_split_amt"):
        reason = str(txn.get("reason_cd") or "")
        if reason in ("", "__NONE__"):
            continue
        bucket = grouped.setdefault(reason, {
            "reason_cd": reason,
            "cause_label": cause_for_code(reason).get("cause_label") or reason,
            "accounts": set(), "advisors": set(), "trade_count": 0, "value": 0.0})
        bucket["accounts"].add(str(txn.get("acct_key")))
        bucket["advisors"].add(str(txn.get("advisor_sid")))
        bucket["trade_count"] += 1
        bucket["value"] += _num(txn.get("non_credited_amt")) or _num(txn.get("pre_split_amt"))

    rows = sorted(
        ({"reason_cd": b["reason_cd"], "cause_label": b["cause_label"],
          "account_count": len(b["accounts"]), "trade_count": b["trade_count"],
          "advisor_count": len(b["advisors"]), "value": round(b["value"], 2)}
         for b in grouped.values()),
        key=lambda r: -r["value"])
    totals = None
    if rows:
        totals = {"reason_cd": "", "cause_label": "Total",
                  "account_count": sum(r["account_count"] for r in rows),
                  "trade_count": sum(r["trade_count"] for r in rows),
                  "advisor_count": sum(r["advisor_count"] for r in rows),
                  "value": round(sum(r["value"] for r in rows), 2)}

    return make_payload(
        "noncredited", params,
        title="Non-Credited Revenue by Cause",
        subtitle=f"Month {month} · transactions with a reason code",
        columns=[col("reason_cd", "Code"), col("cause_label", "Cause"),
                 col("account_count", "Accounts", "int"),
                 col("trade_count", "Trades", "int"),
                 col("advisor_count", "Advisors", "int"),
                 col("value", "Non-Credited Value", "money")],
        rows=rows, totals=totals,
        footnotes=[f"{r['reason_cd']}: {cause_for_code(r['reason_cd']).get('description') or ''}"
                   for r in rows],
        filename_stem=f"noncredited_{month}")


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------

def provide_exceptions(params: dict) -> dict:
    from fastapi import HTTPException

    from app.api.routers.insights import exceptions as exceptions_endpoint

    from_month, to_month = _require(params, "from", "to")
    severity = params.get("severity")
    try:
        data = exceptions_endpoint(from_month=from_month, to_month=to_month,
                                   severity=severity)
    except HTTPException as exc:
        raise ExportParamError(str(exc.detail)) from exc

    rows = []
    for entry in data.get("exceptions") or []:
        citation = entry.get("citation") or {}
        advisor = entry.get("advisor_sid") or ""
        if entry.get("advisor_name"):
            advisor = f"{entry['advisor_name']} ({advisor})"
        rows.append({
            "severity": entry.get("severity"),
            "advisor": advisor,
            "issue": entry.get("issue"),
            "detail": entry.get("detail"),
            "impact_amt": entry.get("impact_amt"),
            "rule_citation": (citation.get("rule_name") or citation.get("rule_key")
                              or entry.get("rule_key")
                              or "Observation — no rule matched"),
        })

    subtitle = _transition_text(from_month, to_month)
    if severity:
        subtitle += f" · Severity: {severity}"
    return make_payload(
        "exceptions", params,
        title="Exceptions Worklist", subtitle=subtitle,
        columns=[col("severity", "Severity"), col("advisor", "Advisor"),
                 col("issue", "Issue"), col("detail", "Detail"),
                 col("impact_amt", "Impact", "money", signed=True),
                 col("rule_citation", "Rule Citation")],
        rows=rows,
        footnotes=["Sorted Critical → Info, then by absolute impact. Rows with "
                   "no rule are observations at INFO severity."],
        filename_stem=f"exceptions_{from_month}-{to_month}")


# ---------------------------------------------------------------------------
# insights
# ---------------------------------------------------------------------------

def provide_insights(params: dict) -> dict:
    from app.insights.store import get_insight_store

    from_month, to_month = _require(params, "from", "to")
    advisor = str(params.get("advisor") or "all")
    store = get_insight_store()
    run = store.latest_run_for(advisor, from_month, to_month)

    preamble: list[str] = []
    rows: list[dict] = []
    if run is not None and run.get("status") == "COMPLETE":
        import json as _json

        if run.get("narrative"):
            preamble.append(str(run["narrative"]))
        for bullet in _json.loads(run.get("bullets_json") or "[]"):
            preamble.append(f"• {bullet}")
        for finding in store.run_findings(run["run_id"]):
            rows.append({
                "rank_order": finding.get("rank_order"),
                "title": finding.get("title"),
                "driver": finding.get("driver_code") or "",
                "severity": finding.get("severity") or "INFO",
                "impact_amt": finding.get("impact_amt"),
                "summary": finding.get("summary"),
            })

    return make_payload(
        "insights", params,
        title="AI Insights",
        subtitle=_transition_text(from_month, to_month)
                 + f" · Scope: {advisor}",
        columns=[col("rank_order", "#", "int"), col("title", "Finding"),
                 col("driver", "Driver"), col("severity", "Severity"),
                 col("impact_amt", "Impact", "money", signed=True),
                 col("summary", "Summary")],
        rows=rows, preamble=preamble,
        footnotes=["Findings from the latest stored insight run for this "
                   "transition; impact figures are computed from rule "
                   "evaluation over loaded data."],
        filename_stem=f"insights_{from_month}-{to_month}_{advisor}")


# ---------------------------------------------------------------------------

PROVIDERS: dict[str, Callable[[dict], dict]] = {
    "dashboard_table": provide_dashboard_table,
    "noncredited": provide_noncredited,
    "exceptions": provide_exceptions,
    "insights": provide_insights,
}


def build_payload(section: str, params: dict) -> dict:
    provider = PROVIDERS.get(section)
    if provider is None:
        raise ExportParamError(
            f"unknown section '{section}' (expected {'|'.join(SECTIONS)})")
    return provider(dict(params or {}))

"""The normalized table payload every export provider returns and every
renderer consumes.

Shape (a plain dict — providers build it with ``make_payload``):

    {
      "section":   "dashboard_table",
      "title":     "Product Contribution",
      "subtitle":  "Transition 202604 → 202605 · View: All products",
      "columns":   [{"key","label","type","signed"?}, ...],
      "rows":      [ {key: raw value, ...}, ... ],   # raw numbers, never strings
      "totals":    {key: raw value, ...} | None,
      "preamble":  ["narrative paragraph", "• bullet", ...],
      "footnotes": ["accounts: ...", ...],           # definitions, one source
      "footer":    {"source","generated_at","rule_set_version"},
      "filename_stem": "dashboard_table_202604-202605_all",
    }

Column ``type`` ∈ text | int | money | pct.  ``signed: True`` marks a change
column: renderers colour it green/red and parenthesise negatives.  An empty
``rows`` list means "no data for this selection" — renderers say exactly that
and never fabricate a row.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

# Visual tokens from docs/ui/MOCKUP_ROUND_A_DASHBOARD.html — one place.
NAVY = "#16365C"
POSITIVE_GREEN = "#157F4C"
NEGATIVE_RED = "#B3261E"

NO_DATA_TEXT = "No data for this selection."


def col(key: str, label: str, type_: str = "text", *, signed: bool = False) -> dict:
    return {"key": key, "label": label, "type": type_, "signed": signed}


def build_footer(section: str, params: dict) -> dict:
    """Traceability footer carried by EVERY export: source (app + section +
    params), generation timestamp, rule set version (latest PUBLISHED)."""
    from app.rules.store import get_rule_store

    version = get_rule_store().latest_version("PUBLISHED")
    return {
        "source": ("pce-practice-demo POST /api/export section=" + section
                   + " params=" + json.dumps(params, sort_keys=True, default=str)),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rule_set_version": (version["version_id"] if version
                             else "(no published rule set)"),
    }


def make_payload(section: str, params: dict, *, title: str, subtitle: str,
                 columns: list[dict], rows: list[dict],
                 totals: dict | None = None,
                 preamble: list[str] | None = None,
                 footnotes: list[str] | None = None,
                 filename_stem: str | None = None) -> dict:
    return {
        "section": section, "title": title, "subtitle": subtitle,
        "columns": columns, "rows": rows, "totals": totals,
        "preamble": preamble or [], "footnotes": footnotes or [],
        "footer": build_footer(section, params),
        "filename_stem": filename_stem or section,
    }


def fmt_display(value: Any, type_: str) -> str:
    """Human formatting for pdf/pptx: thousands separators, negatives in
    parentheses (money and pct), blanks for None."""
    if value is None or value == "":
        return "—" if type_ != "text" else ""
    if type_ == "text":
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if type_ == "int":
        body = f"{abs(number):,.0f}"
    elif type_ == "pct":
        body = f"{abs(number):,.2f}%"
    else:  # money
        body = f"{abs(number):,.2f}"
    return f"({body})" if number < 0 else body


def is_negative(value: Any) -> bool:
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False

"""Round A1 task 1.4 — the ONE server-side source of every explanatory string
the UI shows as a tooltip.

The client wants tooltips broadly; if these strings lived in the frontend the
same term would end up explained three different ways on three screens. The
dashboard's metric definitions here are ALSO what GET /api/dashboard/definitions
returns — one source, restated nowhere.

Terms are keyed by a stable term code the UI references:
  metric.<name> | driver.<DRIVER_CODE> | severity.<LEVEL> |
  provenance.<CHIP> | noncredited.<REASON_CD>
"""
from __future__ import annotations

# Task 3 definitions — "and they must be consistent everywhere".
METRIC_DEFINITIONS: dict[str, str] = {
    "accounts": "Distinct accounts with credited revenue in the month for that product.",
    "trades": "Count of credited transactions in the month.",
    "revenue": "Sum of post-split credited amount where the reason code is empty "
               "(reason_cd = '__NONE__').",
    "aum": "Assets under management: sum of month-end balances from account_month "
           "for accounts holding that product.",
    "share": "Share of the selected view's total credited revenue for the to-month. "
             "In a filtered view (recurring / non-recurring only) the share is of the "
             "filtered total, so the column always sums to 100%.",
}

# Task 2 severity levels (assigned at extraction, editable on the rule).
SEVERITY_DEFINITIONS: dict[str, str] = {
    "CRITICAL": "The plan requires something the data contradicts and money is moving "
                "now — act immediately.",
    "HIGH": "A material breach or loss the advisor may not know about — review soon.",
    "MODERATE": "An expected business event with material impact — worth tracking.",
    "LOW": "A positive or minor event — informational, no action expected.",
    "INFO": "An observation that explains a movement; nothing to act on.",
}

# Provenance chips on findings and evidence.
PROVENANCE_DEFINITIONS: dict[str, str] = {
    "REAL": "The figure was read directly from a query result over loaded data.",
    "DERIVED": "The figure was computed from query results (a difference or ratio) — "
               "traceable, but not a single stored value.",
    "DUMMY": "The row comes from generated placeholder data (data_source='DUMMY') — "
             "illustrative only, never a client fact.",
}


def build_glossary() -> dict:
    """Every term the UI needs to explain, keyed by stable term code. Driver
    definitions are resolved live from the rule store so a rename or a newly
    compiled rule shows up without a deploy."""
    from app.rules.drivers import list_drivers
    from app.shared.reason_codes import REASON_CODES

    terms: dict[str, dict] = {}
    for name, definition in METRIC_DEFINITIONS.items():
        terms[f"metric.{name}"] = {"term": name, "kind": "metric",
                                   "definition": definition}
    for driver in list_drivers():
        terms[f"driver.{driver['driver_code']}"] = {
            "term": driver["driver_label"], "kind": "driver",
            "definition": driver["driver_definition"],
            "driver_code": driver["driver_code"], "rule_key": driver["rule_key"]}
    for level, definition in SEVERITY_DEFINITIONS.items():
        terms[f"severity.{level}"] = {"term": level.title(), "kind": "severity",
                                      "definition": definition}
    for chip, definition in PROVENANCE_DEFINITIONS.items():
        terms[f"provenance.{chip}"] = {"term": chip, "kind": "provenance",
                                       "definition": definition}
    for code, spec in REASON_CODES.items():
        terms[f"noncredited.{code}"] = {
            "term": spec["cause_label"], "kind": "noncredited",
            "definition": spec["description"], "reason_cd": code,
            "cause": spec["cause"]}
    return {"terms": terms, "term_count": len(terms)}

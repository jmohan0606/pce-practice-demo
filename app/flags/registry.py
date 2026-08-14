"""Round A2B task 7 — the ONE place feature-flag metadata lives.

Every flag the app has: key (dot-namespaced; parent.child inherits), display
name, description, group, parent, always_on, dependency note, and cost-hint
kind. The store (app/flags/store.py) holds STATE (enabled + notes + history);
this module holds IDENTITY. The settings page, the API serializer and the
``require_feature`` dependency all resolve here — flag names and descriptions
are never restated in a component.

Flag count: 26 (ceiling 30). The spec's dashboard group said "7" but
enumerated 8 sections — reconciled against the codebase honestly: Round A1
added the per-cause non-credited detail as its own sub-flag, so the dashboard
group carries 8 flags and the app total is 26.
"""
from __future__ import annotations

from fastapi import HTTPException

GROUPS = (
    ("dashboard", "Practice Management Dashboard"),
    ("advisor", "iPerform Advisor AI Insights"),
    ("docs", "Documents & Rules"),
    ("rules", "Rule Versions"),
    ("global", "Global"),
)

# key -> {name, description, group, parent, always_on, dep, cost}
# cost kinds: None | "insights_avg" | "drilldown_avg" | "coach_avg" | "chat_static"
FLAGS: dict[str, dict] = {
    "dashboard.chart": {
        "name": "Revenue Bar Chart",
        "description": "Month-over-month bars with transition arrows and AUM.",
        "group": "dashboard", "parent": None, "always_on": False,
        "dep": "Required by: Product Table, AI Insights, Drivers, Non-Credited, "
               "Exceptions — turning this off leaves no way to select a transition.",
        "cost": None,
    },
    "dashboard.table": {
        "name": "Product Contribution Table",
        "description": "Accounts, trades and revenue per product with month-over-month deltas.",
        "group": "dashboard", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "dashboard.table.top_bottom": {
        "name": "Top / Bottom Advisors",
        "description": "Per-product ranking of the ten highest and lowest contributing advisors.",
        "group": "dashboard", "parent": "dashboard.table", "always_on": False,
        "dep": None, "cost": None,
    },
    "dashboard.insights": {
        "name": "AI Insights",
        "description": "Generated narrative with rule citations for the selected transition.",
        "group": "dashboard", "parent": None, "always_on": False, "dep": None,
        "cost": "insights_avg",
    },
    "dashboard.drivers": {
        "name": "Drivers",
        "description": "Ranked drivers with evidence, By Driver and By Product views.",
        "group": "dashboard", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "dashboard.noncredited": {
        "name": "Non-Credited Revenue Analysis",
        "description": "Why revenue did not count, grouped by reason code.",
        "group": "dashboard", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "dashboard.noncredited.detail": {
        "name": "Non-Credited per-cause detail",
        "description": "Per-cause detail modals — each cause has its own table shape.",
        "group": "dashboard", "parent": "dashboard.noncredited", "always_on": False,
        "dep": None, "cost": None,
    },
    "dashboard.exceptions": {
        "name": "Exceptions",
        "description": "Where the plan expects something the data does not show, with severity.",
        "group": "dashboard", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "advisor.chart_metrics": {
        "name": "Advisor Bar Chart & Metrics",
        "description": "Per-advisor revenue, AUM, NCF, NNM, account lifecycle counts.",
        "group": "advisor", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "advisor.drivers": {
        "name": "Drivers",
        "description": "The advisor's stored findings for the selected transition.",
        "group": "advisor", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "advisor.compare": {
        "name": "Compare Two Transitions",
        "description": "Side-by-side driver comparison of two month transitions for one advisor.",
        "group": "advisor", "parent": "advisor.drivers", "always_on": False,
        "dep": None, "cost": None,
    },
    "advisor.peer_ranking": {
        "name": "Peer Ranking",
        "description": "Where this advisor sits in the cohort on revenue, growth and discount rate.",
        "group": "advisor", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "advisor.coaching": {
        "name": "Coaching",
        "description": "Coaching points drawn from GUIDANCE documents, quoted with citations.",
        "group": "advisor", "parent": None, "always_on": False, "dep": None,
        "cost": "coach_avg",
    },
    "advisor.crm_opportunities": {
        "name": "CRM Opportunities",
        "description": "Pipeline data joined through the household relationship. "
                       "Placeholder feed — every row is marked Dummy Data.",
        "group": "advisor", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "docs.manual_rule_authoring": {
        "name": "Manual Rule Authoring",
        "description": "Operator-written rules alongside document-extracted ones.",
        "group": "docs", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "docs.nl_only_rules": {
        "name": "Natural-Language-Only Rules",
        "description": "Rules stated in plain English that never compiled to a plan.",
        "group": "docs", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "docs.conflict_auditor": {
        "name": "Rule Conflict Auditor",
        "description": "Cross-rule contradiction audit before publish.",
        "group": "docs", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "docs.categories_beyond_plan": {
        "name": "Document Categories beyond Plan",
        "description": "GUIDANCE and other non-plan document categories at upload.",
        "group": "docs", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "rules.driver_renaming": {
        "name": "Driver Renaming",
        "description": "Display-label renames that reach every historical finding at read time.",
        "group": "rules", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "global.drilldown": {
        "name": "Drill-Down Panel",
        "description": "Product → advisor → account → transaction chain from any change figure.",
        "group": "global", "parent": None, "always_on": False, "dep": None,
        "cost": "drilldown_avg",
    },
    "global.export": {
        "name": "Export — PDF, PowerPoint, Excel, CSV",
        "description": "Export any section exactly as displayed.",
        "group": "global", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "global.chat": {
        "name": "Chat",
        "description": "Ask questions about the loaded data. Not built yet — "
                       "arrives in a later round; the flag exists so the demo scope "
                       "is settable ahead of it.",
        "group": "global", "parent": None, "always_on": False, "dep": None,
        "cost": "chat_static",
    },
    "global.trace": {
        "name": "Trace & Cost",
        "description": "LLM turn log, token counts and cost per run.",
        "group": "global", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "global.tooltips": {
        "name": "Tooltips",
        "description": "Hover definitions for metrics, drivers, severities and provenance chips.",
        "group": "global", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "global.storage_regeneration": {
        "name": "Storage & Regeneration",
        "description": "Stored-run reuse and the Regenerate buttons.",
        "group": "global", "parent": None, "always_on": False, "dep": None, "cost": None,
    },
    "global.numeric_guardrail": {
        "name": "Numeric Verification Guardrail",
        "description": "Every figure in generated prose must trace to a query result.",
        "group": "global", "parent": None, "always_on": True,
        "dep": "Cannot be turned off. Without it a narrative could contain a "
               "figure nobody computed.",
        "cost": None,
    },
}

FLAG_CEILING = 30
assert len(FLAGS) <= FLAG_CEILING, "flag ceiling exceeded — is this really a section?"

PRESETS: dict[str, dict] = {
    "full": {
        "name": "Full",
        "description": "Everything on. Use this for internal testing and verification.",
        "off": frozenset(),
    },
    "client_demo": {
        "name": "Client Demo",
        "description": "The agreed demo scope. Trace, dummy CRM data and unbuilt chat hidden.",
        "off": frozenset({"global.trace", "advisor.crm_opportunities", "global.chat"}),
    },
    "minimal": {
        "name": "Minimal",
        "description": "Chart and product table only. Nothing AI-generated.",
        "off": frozenset(
            k for k, meta in FLAGS.items()
            if not meta["always_on"]
            and k not in ("dashboard.chart", "dashboard.table",
                          "global.tooltips", "global.export")),
    },
}


def require_feature(key: str):
    """FastAPI dependency factory: 409 BEFORE any query executes when the flag
    (or its parent) is off. Applied at the router/endpoint level so a hidden
    section's queries genuinely do not run."""
    if key not in FLAGS:
        raise ValueError(f"unknown feature flag '{key}'")

    def _dep() -> None:
        from app.flags.store import get_flag_store

        store = get_flag_store()
        if not store.effective_enabled(key):
            note = store.flag_note(key) or store.flag_note(FLAGS[key]["parent"] or "")
            raise HTTPException(
                status_code=409,
                detail={"feature_disabled": key,
                        "reason": (note or {}).get("reason")
                        or "feature turned off in Settings"})

    _dep.__name__ = f"require_feature_{key.replace('.', '_')}"
    return _dep

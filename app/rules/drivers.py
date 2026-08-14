"""Round A1 task 1 — driver identity, labels and definitions.

Identity model:
- ``driver_code`` is the STABLE identity — uppercase slug, stored on findings
  and rules, never edited (``NEW_BILLING``, ``FEE_RATE``).
- ``driver_label`` is the DISPLAY name — resolved at read time, so renaming a
  driver changes what every historical finding shows with no regeneration and
  no rewriting of stored text. Resolution order:
    1. the operator's label override (RuleStore driver-label registry, durable)
    2. the label carried by a rule bearing that driver_code (latest version)
    3. the built-in agent driver table below
    4. the titleized code (honest last resort — never blank)
- ``driver_definition`` explains what the driver MEANS (chip tooltips). For
  tech-written rules it is authored in the seed; for document-derived rules the
  Rule Compiler drafts it from the rule statement; the agent table below covers
  the miner's rule-less driver tags.
"""
from __future__ import annotations

import re

# The miner's rule-less driver vocabulary (promoted from the Round F frontend
# table frontend/lib/driverDefinitions.ts — the server is now the one source;
# GET /api/drivers and /api/glossary serve these).
AGENT_DRIVERS: dict[str, dict] = {
    "NEW_BILLING": {
        "label": "New Billing",
        "definition": "An account that held a balance in the prior month but produced no "
                      "credited revenue, and produced credited revenue this month. Distinct "
                      "from a new account, which did not exist before."},
    "NEW_ACCOUNTS": {
        "label": "New Accounts",
        "definition": "An account that did not exist in the prior month and produced "
                      "credited revenue this month."},
    "LOST_ACCOUNTS": {
        "label": "Lost Accounts",
        "definition": "An account that produced credited revenue in the prior month and "
                      "produces none this month — closed or zeroed."},
    "RETAINED_ACCOUNTS": {
        "label": "Retained Accounts",
        "definition": "An account with credited revenue in both the prior month and this "
                      "month — neither new, newly billing, transferred in, nor lost."},
    "TRANSFERS": {
        "label": "Transfers",
        "definition": "An account that moved into or out of this advisor's book from or to "
                      "another advisor."},
    "FEE_RATE": {
        "label": "Fee Rate",
        "definition": "The effective fee rate on an account or product changed — the same "
                      "balance billed at a different rate."},
    "MARKET": {
        "label": "Market",
        "definition": "Market movement changed billable balances without client money "
                      "moving in or out."},
    "FLOWS": {
        "label": "Flows",
        "definition": "Client money moved in or out of existing accounts, changing the "
                      "billable balance."},
    "ONE_TIME": {
        "label": "One-Time",
        "definition": "A non-recurring item — a one-off fee, adjustment, or correction not "
                      "expected to repeat next month."},
    "INHERITED": {
        "label": "Inherited",
        "definition": "Revenue on accounts inherited from another advisor."},
    "REFERRALS": {
        "label": "Referrals",
        "definition": "Revenue connected to a referral arrangement."},
    "PERIOD_LENGTH": {
        "label": "Period Length",
        "definition": "The billing periods being compared differ in length, changing the "
                      "amount billed."},
    "CALENDAR": {
        "label": "Calendar",
        "definition": "A calendar effect — day counts, billing dates, or month boundaries — "
                      "changed the amount billed."},
    "MIX": {
        "label": "Mix",
        "definition": "The blend of products or accounts shifted toward higher- or "
                      "lower-fee holdings."},
    "EXTRACTION": {
        "label": "Extraction",
        "definition": "A placeholder driver on extractor output kept for operator review — "
                      "not a revenue movement."},
    "OTHER": {
        "label": "Other",
        "definition": "A movement that does not fit a standard driver category — see the "
                      "finding's evidence rows."},
}


def slug_driver_code(label: str | None) -> str:
    """"New Billing" -> NEW_BILLING. Stable, uppercase, never edited."""
    text = str(label or "").strip()
    if not text:
        return "OTHER"
    code = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return code or "OTHER"


def _store():
    from app.rules.store import get_rule_store

    return get_rule_store()


def _rules_bearing_codes() -> dict[str, dict]:
    """driver_code -> the newest rule bearing it (latest published version
    first, then drafts) — the rule supplies label/definition/citation."""
    store = _store()
    by_code: dict[str, dict] = {}
    pools: list[list[dict]] = []
    latest = store.latest_version("PUBLISHED")
    if latest is not None:
        pools.append(store.version_rules(latest["version_id"]))
    pools.append(store.drafts())
    for pool in pools:
        for rule in pool:
            code = rule.get("driver_code") or slug_driver_code(rule.get("driver_tag"))
            by_code.setdefault(code, rule)
    return by_code


def resolve_driver_label(driver_code: str | None) -> str:
    """Read-time label resolution — the ONLY place display names come from."""
    code = str(driver_code or "OTHER")
    override = _store().driver_label_override(code)
    if override:
        return override
    rule = _rules_bearing_codes().get(code)
    if rule is not None:
        label = rule.get("driver_label") or rule.get("driver_tag")
        if label:
            return str(label)
    if code in AGENT_DRIVERS:
        return AGENT_DRIVERS[code]["label"]
    return code.replace("_", " ").title()


def resolve_driver_definition(driver_code: str | None) -> str | None:
    code = str(driver_code or "OTHER")
    rule = _rules_bearing_codes().get(code)
    if rule is not None and rule.get("driver_definition"):
        return str(rule["driver_definition"])
    if code in AGENT_DRIVERS:
        return AGENT_DRIVERS[code]["definition"]
    if rule is not None and rule.get("statement"):
        return str(rule["statement"])
    return None


def _rule_source(rule: dict) -> str | dict:
    citations = rule.get("citations") or []
    if citations:
        return citations[0]
    return "TECH_TEAM_WRITTEN"


def list_drivers() -> list[dict]:
    """Every known driver: rule-bearing drivers first (with their rule_key and
    document citation when they have one), then the agent-only vocabulary."""
    store = _store()
    out: list[dict] = []
    seen: set[str] = set()
    for code, rule in sorted(_rules_bearing_codes().items()):
        out.append({
            "driver_code": code,
            "driver_label": store.driver_label_override(code)
            or rule.get("driver_label") or rule.get("driver_tag")
            or (AGENT_DRIVERS.get(code, {}).get("label")
                or code.replace("_", " ").title()),
            "driver_definition": rule.get("driver_definition")
            or AGENT_DRIVERS.get(code, {}).get("definition")
            or rule.get("statement"),
            "rule_key": rule.get("rule_key"),
            "source": _rule_source(rule),
        })
        seen.add(code)
    for code, spec in sorted(AGENT_DRIVERS.items()):
        if code in seen:
            continue
        out.append({
            "driver_code": code,
            "driver_label": store.driver_label_override(code) or spec["label"],
            "driver_definition": spec["definition"],
            "rule_key": None,
            "source": "TECH_TEAM_WRITTEN",
        })
    return out

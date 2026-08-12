"""Rule evaluation service — runs compiled plans through the tiered graph client.

Evaluation goes through ``get_graph_client().run_query("rules_evaluate_plan")``
(mock-tier implementation registered in app/graph/queries/rules_evaluate.py),
so the same call path serves mock and, later, a live TigerGraph.

``evaluate_rule_set`` honours B3.7 ordering: rules run in ``evaluation_order``,
and account keys matched by an earlier TRANSFER rule (driving vertex
phx_dm_pce_account_transfer) are EXCLUDED from later account-grain populations —
so a transferred account is never counted as lost.

Round F: a rule may also carry ``exclude_matched_of: [rule_code, ...]`` —
account keys matched by those earlier rules in the same evaluation pass are
excluded from its population. NEW_BILLING uses it to exclude accounts already
claimed by NEW_ACCOUNT (an account opened this month is new, not newly
billing).
"""
from __future__ import annotations

from app.rules.compiler import CompileError, compile_rule
from app.rules.store import get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.rules.service")

_TRANSFER_VERTEX = "phx_dm_pce_account_transfer"


def _run_plan(plan: dict, params: dict) -> dict:
    import app.graph.queries.rules_evaluate  # noqa: F401 — registers the mock impl
    from app.graph.client import get_graph_client

    result = get_graph_client().run_query(
        "rules_evaluate_plan", {"plan": plan, "params": params}
    )
    rows = result.get("results") or [{}]
    return rows[0]


def evaluate_rule(rule: dict, month: str | None = None, advisor_sid: str | None = None,
                  exclude_keys: list[str] | None = None) -> dict:
    """Evaluate one rule. Uncompilable → an honest error payload, never a crash."""
    compiled = compile_rule(rule)
    if isinstance(compiled, CompileError):
        return {"rule_code": rule.get("rule_code"), "evaluated": False,
                "error": str(compiled), "matched": [], "matched_count": 0}
    params: dict = {}
    if month:
        params["month"] = month
    if advisor_sid:
        params["advisor_sid"] = advisor_sid
    if exclude_keys:
        params["exclude_keys"] = list(exclude_keys)
    try:
        outcome = _run_plan(compiled.plan, params)
    except Exception as exc:  # noqa: BLE001 — honest failure, never fabricated
        return {"rule_code": rule.get("rule_code"), "evaluated": False,
                "error": f"{type(exc).__name__}: {exc}", "matched": [], "matched_count": 0}
    return {
        "rule_code": rule.get("rule_code"),
        "rule_key": rule.get("rule_key"),
        "evaluated": True,
        "month": month,
        "advisor_sid": advisor_sid,
        "vertex": compiled.plan["vertex"],
        **outcome,
    }


def evaluate_rule_set(version_id: str, month: str | None = None,
                      advisor_sid: str | None = None) -> dict:
    """Evaluate every rule of a version in evaluation_order, excluding accounts
    claimed by earlier transfer rules from later account-grain populations."""
    store = get_rule_store()
    version = store.version(version_id)
    if version is None:
        raise ValueError(f"unknown rule-set version {version_id!r}")
    rules = store.version_rules(version["version_id"])
    transferred_keys: set[str] = set()
    matched_by_code: dict[str, set[str]] = {}
    results = []
    for rule in rules:
        exclude: set[str] = set(transferred_keys) if rule.get("grain") == "account" else set()
        # Round F: explicit claims — keys matched by the named earlier rules
        # (e.g. NEW_BILLING excludes NEW_ACCOUNT's accounts).
        for code in rule.get("exclude_matched_of") or []:
            exclude |= matched_by_code.get(code, set())
        outcome = evaluate_rule(rule, month=month, advisor_sid=advisor_sid,
                                exclude_keys=sorted(exclude) if exclude else None)
        outcome["evaluation_order"] = rule.get("evaluation_order")
        results.append(outcome)
        if outcome.get("evaluated"):
            matched_by_code.setdefault(rule["rule_code"], set()).update(
                str(entry["key"]) for entry in outcome.get("matched", []))
            if outcome.get("vertex") == _TRANSFER_VERTEX:
                # transfer rules match transfer rows; the excluded entity is the account.
                transferred_keys |= {entry["key"] for entry in outcome.get("matched", [])}
    return {"version_id": version["version_id"], "month": month,
            "advisor_sid": advisor_sid, "results": results}

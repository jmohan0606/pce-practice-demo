"""Rule evaluation service — runs compiled plans through the tiered graph client.

Evaluation goes through ``get_graph_client().run_query("rules_evaluate_plan")``
(mock-tier implementation registered in app/graph/queries/rules_evaluate.py),
so the same call path serves mock and, later, a live TigerGraph.

``evaluate_rule_set`` honours B3.7 ordering: rules run in ``evaluation_order``,
and exclusion between rules happens ONE way — a rule that needs it declares
``exclude_matched_of: [rule_code, ...]``: account keys matched by those earlier
rules in the same evaluation pass are excluded from its population. NEW_BILLING
uses it to exclude accounts already claimed by NEW_ACCOUNT; LOST_ACCOUNT uses it
to exclude transferred accounts (Round H task 1 — this replaces the implicit
``transferred_keys`` accumulation, which silently excluded IN's matches from OUT
at practice scope where both rules see the same transfer rows).
"""
from __future__ import annotations

from app.rules.compiler import SCOPES, CompileError, derive_scopes, translate_plan
from app.rules.store import get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.rules.service")


def rule_scopes(rule: dict) -> list[str]:
    """The scopes a rule may be evaluated at: the explicit ``scopes`` list when
    the rule carries one (compiler-set or human-overridden), otherwise derived
    from its plan(s) — a plan referencing :advisor_sid is restricted to the
    scopes that supply it; no scope parameter → every scope."""
    explicit = rule.get("scopes")
    if explicit:
        return [s for s in SCOPES if s in explicit]
    return derive_scopes(rule.get("plan"), rule.get("plan_by_scope"))


def plan_for_scope(rule: dict, scope: str | None) -> dict | None:
    """Round G 1.3: a rule may carry ``plan_by_scope`` (scope → plan JSON);
    evaluation at that scope uses the scope's plan, falling back to ``plan``."""
    by_scope = rule.get("plan_by_scope") or {}
    if scope and isinstance(by_scope, dict) and isinstance(by_scope.get(scope), dict):
        return by_scope[scope]
    return rule.get("plan")


def _compile_for_scope(rule: dict, scope: str | None):
    plan_json = plan_for_scope(rule, scope)
    if not isinstance(plan_json, dict):
        return CompileError(rule.get("rule_code") or "(unnamed rule)", "vertex",
                            "rule has no compiled plan — run the Rule Compiler first")
    return translate_plan(rule.get("rule_code") or "(unnamed rule)",
                          rule.get("grain") or "", plan_json)


def _run_plan(plan: dict, params: dict) -> dict:
    import app.graph.queries.rules_evaluate  # noqa: F401 — registers the mock impl
    from app.graph.client import get_graph_client

    result = get_graph_client().run_query(
        "rules_evaluate_plan", {"plan": plan, "params": params}
    )
    rows = result.get("results") or [{}]
    return rows[0]


def evaluate_rule(rule: dict, month: str | None = None, advisor_sid: str | None = None,
                  exclude_keys: list[str] | None = None,
                  scope: str | None = None) -> dict:
    """Evaluate one rule (with the scope's plan when it has one).
    Uncompilable → an honest error payload, never a crash."""
    compiled = _compile_for_scope(rule, scope)
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
        "scope": scope,
        "vertex": compiled.plan["vertex"],
        **outcome,
    }


def evaluate_rule_set(version_id: str, month: str | None = None,
                      advisor_sid: str | None = None,
                      scope: str | None = None) -> dict:
    """Evaluate every rule of a version in evaluation_order at one scope.
    Exclusion is explicit only: a rule's ``exclude_matched_of`` names the
    earlier rules whose matched account keys are removed from its population.

    Round G task 1: rules whose ``scopes`` do not include the evaluation scope
    are NOT evaluated — they come back ``skipped`` with a skip_reason. Skipped
    is a normal, expected state, distinct from failed. When ``scope`` is not
    given it derives from the parameters: advisor_sid supplied → "advisor",
    otherwise "practice"."""
    store = get_rule_store()
    version = store.version(version_id)
    if version is None:
        raise ValueError(f"unknown rule-set version {version_id!r}")
    if scope is None:
        scope = "advisor" if advisor_sid else "practice"
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r} — expected one of {', '.join(SCOPES)}")
    rules = store.version_rules(version["version_id"])
    matched_by_code: dict[str, set[str]] = {}
    results = []
    for rule in rules:
        if scope not in rule_scopes(rule):
            results.append({
                "rule_code": rule.get("rule_code"),
                "rule_key": rule.get("rule_key"),
                "evaluated": False,
                "skipped": True,
                "skip_reason": f"not applicable at {scope} scope",
                "scope": scope,
                "matched": [], "matched_count": 0,
                "evaluation_order": rule.get("evaluation_order"),
            })
            continue
        # Explicit claims only — keys matched by the named earlier rules
        # (e.g. NEW_BILLING excludes NEW_ACCOUNT's accounts, LOST_ACCOUNT
        # excludes both transfer rules' accounts).
        exclude: set[str] = set()
        for code in rule.get("exclude_matched_of") or []:
            exclude |= matched_by_code.get(code, set())
        outcome = evaluate_rule(rule, month=month, advisor_sid=advisor_sid,
                                exclude_keys=sorted(exclude) if exclude else None,
                                scope=scope)
        outcome["evaluation_order"] = rule.get("evaluation_order")
        results.append(outcome)
        if outcome.get("evaluated"):
            matched_by_code.setdefault(rule["rule_code"], set()).update(
                str(entry["key"]) for entry in outcome.get("matched", []))
    return {"version_id": version["version_id"], "month": month,
            "advisor_sid": advisor_sid, "scope": scope, "results": results}


def never_fired(version_id: str, months: list[str] | None = None) -> dict:
    """Round H 2.4: a rule evaluated with ZERO matches across every month and
    every scope is either wrong or inapplicable (PARTIAL_PERIOD was both, for a
    round, unnoticed). Evaluates the version's rules at practice scope and at
    advisor scope for every advisor, across ``months`` (default: every month in
    the data), and returns the rules that never matched — with their scopes, so
    a rule that CANNOT fire is obvious without a code read."""
    from app.graph.foundation_store import get_foundation_store

    store = get_rule_store()
    version = store.version(version_id)
    if version is None:
        raise ValueError(f"unknown rule-set version {version_id!r}")
    fstore = get_foundation_store()
    if not fstore.available():
        fstore.load()
    if months is None:
        months = sorted(fstore.all_vertices("phx_dm_pce_month"))
    advisors = sorted(fstore.all_vertices("phx_dm_pce_advisor"))
    total_matched: dict[str, int] = {}
    evaluated_anywhere: dict[str, bool] = {}
    for month in months:
        passes = [{"advisor_sid": None, "scope": "practice"}] + [
            {"advisor_sid": sid, "scope": "advisor"} for sid in advisors]
        for p in passes:
            outcome = evaluate_rule_set(version["version_id"], month=month, **p)
            for r in outcome["results"]:
                code = r["rule_code"]
                total_matched.setdefault(code, 0)
                if r.get("evaluated"):
                    evaluated_anywhere[code] = True
                    total_matched[code] += int(r.get("matched_count") or 0)
    rules = store.version_rules(version["version_id"])
    out = []
    for rule in rules:
        code = rule["rule_code"]
        if total_matched.get(code, 0) == 0:
            out.append({
                "rule_code": code, "rule_key": rule.get("rule_key"),
                "rule_name": rule.get("rule_name"),
                "scopes": rule_scopes(rule),
                "evaluated_anywhere": evaluated_anywhere.get(code, False),
                "total_matched": 0,
                "note": ("never evaluated at any scope in the period"
                         if not evaluated_anywhere.get(code) else
                         "evaluated at every applicable scope and month with "
                         "zero matches — the rule is either wrong or "
                         "inapplicable to this data"),
            })
    return {"version_id": version["version_id"], "months": months,
            "advisors_checked": len(advisors), "never_fired": out}

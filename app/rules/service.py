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

import threading

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


def applies_to_skip_reason(rule: dict, scope: str, advisor_sid: str | None,
                           group_id: str | None = None) -> str | None:
    """Round C (docs/rules) task 1.1 — ``applies_to`` filtering, BEFORE
    evaluation. Returns a human-readable skip reason when the rule should not
    apply to this evaluation, else None.

    Distinct from ``scopes`` (Round G): scopes says which evaluation scopes a
    rule CAN run at; applies_to says which entities it SHOULD apply to. A rule
    can be ADVISOR-applied yet practice-evaluable — both checks run, and either
    produces a skipped (never an error) result."""
    level = rule.get("applies_to") or "ALL"
    key = rule.get("applies_to_key") or None
    if level == "ALL":
        return None
    if level == "PRACTICE":
        if advisor_sid is None and group_id is None:
            return None
        return ("rule applies at PRACTICE (firm) level only — not applicable "
                "to this " + ("advisor" if advisor_sid else "product") + "-level evaluation")
    if level == "ADVISOR":
        if advisor_sid is None:
            return (f"rule applies to advisor {key} only — not applicable to a "
                    f"{scope}-level evaluation" if key else
                    "rule applies at ADVISOR level only — no advisor in this evaluation")
        if key and str(advisor_sid) != str(key):
            return f"rule applies to advisor {key} only — this evaluation is for {advisor_sid}"
        return None
    if level == "PRODUCT":
        if group_id is None:
            return (f"rule applies to product group {key} only — no product group "
                    f"in this evaluation" if key else
                    "rule applies at PRODUCT level only — no product group in this evaluation")
        if key and str(group_id) != str(key):
            return f"rule applies to product group {key} only — this evaluation is for {group_id}"
        return None
    if level == "COMPENSATION_ENGINE":
        # Round 5 Part C: forward-looking scope — stored, displayed and
        # filterable; what a Compensation Engine rule evaluates against is a
        # later decision, so EVERY evaluation skips it with this reason.
        return ("rule applies at COMPENSATION_ENGINE level — its evaluation "
                "target is not yet defined; the rule is stored and displayed "
                "but produces no findings")
    return f"unknown applies_to level {level!r} — rule skipped, not errored"


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
    # Round 10 task 4 — through run_catalog_query: rules_evaluate_plan is an
    # internal LOCAL-COMPUTE entry (Python-interpreted by design; its row
    # reads reach TigerGraph through rule_evaluation_rows).
    from app.graph.queries.catalog import run_catalog_query

    rows = run_catalog_query(
        "rules_evaluate_plan", {"plan": plan, "params": params},
        allow_internal=True)["rows"] or [{}]
    return rows[0]


NL_SKIP_REASON = ("guidance only — no plan by design; the statement is "
                  "injected into the Insights Miner's context instead of "
                  "being evaluated")


def natural_language_only(rule: dict) -> bool:
    """Round C (docs/rules) 5.2 — a guidance rule: no plan BY DESIGN. It is
    never evaluated deterministically and can never produce a computed impact
    figure; its statement shapes the Insights Miner's attention instead."""
    return bool(rule.get("natural_language_only")) and not rule.get("plan")


def evaluate_rule(rule: dict, month: str | None = None, advisor_sid: str | None = None,
                  exclude_keys: list[str] | None = None,
                  scope: str | None = None) -> dict:
    """Evaluate one rule (with the scope's plan when it has one).
    Uncompilable → an honest error payload, never a crash. A
    natural-language-only rule is SKIPPED with its reason — by design, never
    a compile-first error."""
    if natural_language_only(rule):
        return _skip_result(rule, scope or "", NL_SKIP_REASON)
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


def _skip_result(rule: dict, scope: str, reason: str) -> dict:
    return {
        "rule_code": rule.get("rule_code"),
        "rule_key": rule.get("rule_key"),
        "evaluated": False,
        "skipped": True,
        "skip_reason": reason,
        "scope": scope,
        "matched": [], "matched_count": 0,
        "evaluation_order": rule.get("evaluation_order"),
    }


def evaluate_rule_set(version_id: str, month: str | None = None,
                      advisor_sid: str | None = None,
                      scope: str | None = None,
                      group_id: str | None = None) -> dict:
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
        # Round C (docs/rules) task 2.1: an inactive rule is not evaluated in
        # new runs — skipped with the recorded reason, never an error. It
        # remains queryable and historical insights citing it stay valid.
        if rule.get("active") is False:
            results.append(_skip_result(
                rule, scope,
                "rule is inactive"
                + (f" — {rule['active_reason']}" if rule.get("active_reason") else "")))
            continue
        # Round C (docs/rules) task 5.2: a natural-language-only rule has no
        # plan BY DESIGN — skipped with its reason, never a compile-first
        # error. Its statement rides the Insights Miner's context instead.
        if natural_language_only(rule):
            results.append(_skip_result(rule, scope, NL_SKIP_REASON))
            continue
        # Round C (docs/rules) task 1.1: applies_to filtering runs BEFORE the
        # scopes check — "should this rule apply to this entity at all".
        applies_reason = applies_to_skip_reason(rule, scope, advisor_sid, group_id)
        if applies_reason:
            results.append(_skip_result(rule, scope, applies_reason))
            continue
        if scope not in rule_scopes(rule):
            results.append(_skip_result(
                rule, scope, f"not applicable at {scope} scope"))
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


# --------------------------------------------------------------------- Round C (docs/rules)
# task 5.2 — the guidance <-> computed lifecycle. Promotion compiles a
# natural-language rule into a computed rule; demotion removes the plan back
# to guidance. BOTH are version-minting edits for version-bound rules (they
# change whether the rule produces figures) with the recorded reason and
# who/when — the set_active edit→approve→publish pattern. Draft-pool rules
# get their fields updated in place (no version exists to mint yet).

def _now_stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _require_reason(reason: str, action: str) -> str:
    reason = str(reason or "").strip()
    if not reason:
        from app.rules.store import RuleStoreError

        raise RuleStoreError(
            f"a reason is required to {action} — it changes whether the rule "
            f"produces computed figures and becomes the audit record")
    return reason


def promote_rule(rule_key: str, reason: str, changed_by: str = "operator",
                 llm=None) -> dict:
    """Compile a natural-language-only rule into a computed rule. Returns
    {rule, version, note}: version is the newly minted rule-set version for a
    version-bound rule, None for a draft-pool rule (fields update) and None
    when the compiler could not produce a valid plan (the honest failure is
    on the returned rule — nothing publishes)."""
    from app.agents.rule_compiler import compile_rule_with_agent
    from app.rules.store import RuleStoreError

    store = get_rule_store()
    reason = _require_reason(reason, "promote a guidance rule to computed")
    rule = store.get(rule_key)
    if rule is None:
        raise RuleStoreError(f"unknown rule_key {rule_key!r}")
    if not natural_language_only(rule):
        raise RuleStoreError(
            f"{rule_key} is not a guidance-only rule — promote applies only to "
            f"natural-language rules without a plan")
    audit = {"promoted_by": changed_by or "operator", "promoted_at": _now_stamp(),
             "promotion_reason": reason}
    if not rule["version_id"]:
        store.annotate(rule_key, natural_language_only=False, approved=False, **audit)
        compiled = compile_rule_with_agent(rule_key, llm=llm)
        if compiled.get("status") != "COMPILED":
            # honest failure: back to guidance, with the compiler's outcome kept
            store.annotate(rule_key, natural_language_only=True,
                           promotion_error=compiled.get("compile_error")
                           or compiled.get("needs_data_reason"),
                           status="DRAFT", plan=None, explanation=None,
                           needs_data_reason=None)
            return {"rule": store.get(rule_key), "version": None,
                    "note": "the compiler could not produce a valid plan — the "
                            "rule stays guidance-only; see compile_attempts"}
        return {"rule": compiled, "version": None,
                "note": "draft rule — compiled in place; a version mints at publish"}
    draft = store.edit(rule_key, {"natural_language_only": False})
    store.annotate(draft["rule_key"], **audit)
    compiled = compile_rule_with_agent(draft["rule_key"], llm=llm)
    if compiled.get("status") != "COMPILED":
        return {"rule": compiled, "version": None,
                "note": "the compiler could not produce a valid plan — a draft "
                        "was minted with the honest outcome, nothing published; "
                        "retry via recompile or delete the draft"}
    store.approve(draft["rule_key"], approved_by=changed_by or "operator")
    version = store.publish(
        approved_by=changed_by or "operator",
        notes=f"promote {rule.get('rule_code')} to computed: {reason}")
    published = [r for r in store.version_rules(version["version_id"])
                 if r["rule_code"] == rule.get("rule_code")]
    return {"rule": published[0] if published else store.get(draft["rule_key"]),
            "version": version, "note": None}


def demote_rule(rule_key: str, reason: str, changed_by: str = "operator") -> dict:
    """Remove a rule's plan, back to guidance-only. Returns {rule, version,
    note} — version-minting for version-bound rules, fields update for the
    draft pool. The compiled plan is DELIBERATELY discarded (that is the
    point); the prior version keeps its copy forever."""
    from app.rules.store import RuleStoreError

    store = get_rule_store()
    reason = _require_reason(reason, "demote a computed rule to guidance")
    rule = store.get(rule_key)
    if rule is None:
        raise RuleStoreError(f"unknown rule_key {rule_key!r}")
    if not rule.get("plan"):
        raise RuleStoreError(
            f"{rule_key} has no compiled plan — it is already guidance-only "
            f"(or was never compiled); demote applies to computed rules")
    audit = {"demoted_by": changed_by or "operator", "demoted_at": _now_stamp(),
             "demotion_reason": reason}
    if not rule["version_id"]:
        store.annotate(rule_key, natural_language_only=True, plan=None,
                       plan_by_scope=None, explanation=None, compile_error=None,
                       needs_data_reason=None, compiled_evaluated_rows=None,
                       compiled_matched_count=None, compiled_at=None,
                       status="DRAFT", approved=False, **audit)
        return {"rule": store.get(rule_key), "version": None,
                "note": "draft rule — fields updated; a version mints at publish"}
    draft = store.edit(rule_key, {"natural_language_only": True})
    store.annotate(draft["rule_key"], **audit)
    store.approve(draft["rule_key"], approved_by=changed_by or "operator")
    version = store.publish(
        approved_by=changed_by or "operator",
        notes=f"demote {rule.get('rule_code')} to guidance: {reason}")
    published = [r for r in store.version_rules(version["version_id"])
                 if r["rule_code"] == rule.get("rule_code")]
    return {"rule": published[0] if published else store.get(draft["rule_key"]),
            "version": version, "note": None}


# --------------------------------------------------------------------- Round C (docs/rules)
# task 5.3 — the three advisor-scoped manual-rule examples, seeded into the
# DRAFT POOL (the client can see, edit, compile, delete them) and tagged
# MANUALLY_WRITTEN_TECH. Statements only — the Rule Compiler produces each
# plan on demand, and its honest outcome (a simplified attribute where the
# grammar has no day_of_month(), or NEEDS_DATA naming what is missing) is the
# demonstration. Fee Schedule Variance quotes the standard rate through
# STANDARD_MANAGED_FEE_BPS — never a bare literal.

def _manual_example_rules() -> list[dict]:
    from app.shared.fee_schedule import STANDARD_MANAGED_FEE_BPS

    std = int(STANDARD_MANAGED_FEE_BPS)
    return [
        {
            "rule_code": "BILLABLE_DAYS",
            "rule_name": "Billable Days",
            "statement": (
                "An account opened after the first of the month is billed for a "
                "partial period, so its first month's revenue understates the "
                "ongoing run rate. Flag accounts opened in scope (opened_in_scope "
                "= true) with credited revenue in the month, so a first-month "
                "figure is read as a partial-period figure, not the run rate."),
            "worked_example": (
                "An account opened on the 20th bills roughly a third of a full "
                "month; comparing its first month to the next shows growth that "
                "is calendar, not business."),
            "grain": "account",
            "severity": "LOW",
            "severity_reason": "timing artifact — misreads run rate, moves no money",
            "driver_label": "Billable Days",
            "driver_tag": "Billable Days",
            "driver_definition": (
                "First-month revenue on a mid-month account opening covers a "
                "partial billing period and understates the ongoing rate."),
        },
        {
            "rule_code": "QUARTERLY_BILLING_CYCLE",
            "rule_name": "Quarterly Billing Cycle",
            "statement": (
                "A product that bills in one month but not the next produces a "
                "movement that is billing-cycle timing, not business change. "
                "Flag accounts with no credited revenue this month that had "
                "credited revenue in the prior month while still holding a "
                "balance — a billing-cycle gap, distinct from a lost account."),
            "worked_example": (
                "A product billing quarterly posts revenue in March and June "
                "but nothing in April/May; the April 'decline' is timing."),
            "grain": "account",
            "severity": "LOW",
            "severity_reason": "timing, not business change — flags misreads",
            "driver_label": "Quarterly Billing Cycle",
            "driver_tag": "Quarterly Billing Cycle",
            "driver_definition": (
                "Revenue that appears in one month and not the next because of "
                "the product's billing cycle, not a change in the business."),
        },
        {
            "rule_code": "FEE_SCHEDULE_VARIANCE",
            "rule_name": "Fee Schedule Variance",
            "statement": (
                f"An advisor whose BOOK-WIDE average managed fee rate sits below "
                f"the {std} bps standard managed fee schedule is discounting "
                f"across the whole book. Compute the advisor's average annualized "
                f"fee rate in basis points across all managed account-months "
                f"(credited revenue over end balance, annualized) and flag "
                f"advisors whose book-wide average falls below {std} bps. This "
                f"is distinct from the per-account discount rule: it measures "
                f"the whole book, not account by account."),
            "worked_example": (
                f"An advisor billing an average of 120 bps across a $50MM book "
                f"gives up ({std}-120) bps × $50MM ≈ $125K/yr versus the "
                f"standard schedule."),
            "grain": "advisor",
            "severity": "HIGH",
            "severity_reason": "book-wide discounting directly reduces revenue",
            "driver_label": "Fee Schedule Variance",
            "driver_tag": "Fee Schedule Variance",
            "driver_definition": (
                f"The advisor's book-wide average fee rate versus the {std} bps "
                f"standard managed fee schedule — whole-book discounting, "
                f"distinct from per-account discounts."),
        },
    ]


_manual_seed_lock = threading.Lock()


def ensure_manual_examples() -> dict:
    """Idempotent: a rule_code already present anywhere in the store (any
    status, any version — including client-edited or superseded copies) is
    never seeded again, so a restart duplicates nothing. Seeds land as DRAFTs
    with NO plan and generate_query pending — the client compiles (and edits)
    them from the UI; no LLM call happens at seed time."""
    store = get_rule_store()
    with _manual_seed_lock:
        existing_codes = {r.get("rule_code") for r in store.rules.values()}
        seeded = []
        for example in _manual_example_rules():
            if example["rule_code"] in existing_codes:
                continue
            store.add_rule({
                **example,
                "kind": "TRIGGER",
                "status": "DRAFT",
                "provenance": "MANUALLY_WRITTEN_TECH",
                "applies_to": "ADVISOR",
                "applies_to_key": None,
                "active": True,
                "natural_language_only": False,
                "confidence": 1.0,
                "citations": [],
                "missing": None,
                "unclear_notes": None,
                "manual_seed": True,
            }, version_id=None)
            seeded.append(example["rule_code"])
        if seeded:
            _log.info("seeded %d manual example rule(s): %s", len(seeded), seeded)
        return {"seeded": seeded}


def never_fired(version_id: str, months: list[str] | None = None) -> dict:
    """Round H 2.4: a rule evaluated with ZERO matches across every month and
    every scope is either wrong or inapplicable (PARTIAL_PERIOD was both, for a
    round, unnoticed). Evaluates the version's rules at practice scope and at
    advisor scope for every advisor, across ``months`` (default: every month in
    the data), and returns the rules that never matched — with their scopes, so
    a rule that CANNOT fire is obvious without a code read."""
    from app.graph.queries import lookups

    store = get_rule_store()
    version = store.version(version_id)
    if version is None:
        raise ValueError(f"unknown rule-set version {version_id!r}")
    if months is None:
        months = lookups.month_ids()
    advisors = sorted(lookups.advisor_rows(columns="advisor_sid"))
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

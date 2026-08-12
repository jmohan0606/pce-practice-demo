"""B3.7 — the v0 operator-specified rule set, seeded at first startup.

Round E shape: each rule is a plain-English ``statement`` plus an
operator-authored ``plan`` in the Rule Compiler's JSON format, validated
through the SAME five checks every compiled rule passes (including execution
against mock data). Provenance OPERATOR_SPECIFIED, evaluation_order
10,20,20,25,30.

Round F correction: v0 holds ONLY logic the operator supplied because no plan
document states it — exactly five account-lifecycle rules. FEE_REDUCTION_SHARING
was removed (it IS stated in the documents — PCA p.4, SAG p.4, FAQ p.13 — so it
must come from the extractor with its citation, never the seed) and
PARTIAL_PERIOD was removed (client Phase 0 confirmed June is complete: 30
distinct dates, so the rule could never fire). NEW_BILLING was added at order
25: it runs AFTER NEW_ACCOUNT and excludes accounts NEW_ACCOUNT already claimed
(``exclude_matched_of`` — an account opened this month is new, not newly
billing).

``ensure_v0_seed()`` is idempotent: it does nothing when any rule-set version
already exists.
"""
from __future__ import annotations

import threading

from app.rules.store import get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.rules.seed")
_seed_lock = threading.Lock()

V0_RULES: list[dict] = [
    {
        "rule_code": "NEW_ACCOUNT",
        "rule_name": "New Account",
        "statement": "An account opened during the period counts as new for the month "
                     "its first revenue appears.",
        "worked_example": "An account opened in May with $1,200 of May revenue counts as new "
                          "for May.",
        "kind": "TRIGGER",
        "grain": "account",
        "driver_tag": "New Accounts",
        "evaluation_order": 10,
        "plan": {
            "vertex": "phx_dm_pce_account_month",
            "filters": [{"field": "opened_in_scope", "op": "=", "value": True}],
            "compute": {"agg": "sum", "expr": "credited_amt"},
            "trigger": {"op": ">", "value": 0},
            "attribute": None,
            "params": [],
            "explanation": "Reads each account-month flagged as opened in scope, sums its "
                           "credited revenue, and flags accounts whose first revenue appeared.",
            "unsupported": None,
        },
    },
    {
        "rule_code": "ACCOUNT_TRANSFERRED_IN",
        "rule_name": "Account Transferred In",
        "statement": "An account moved to this advisor from another. Checked before "
                     "lost, so a transfer is never counted as a loss.",
        "worked_example": "An account reassigned from advisor A to advisor B in May counts as "
                          "transferred in for B, not as a new account.",
        "kind": "RECORD",
        "grain": "account",
        "driver_tag": "Transfers",
        "evaluation_order": 20,
        # Round G task 1: meaningful firm-wide too — "how many accounts moved
        # between advisors this month" is a practice question, answered by a
        # practice-scope plan that drops the advisor filter.
        "scopes": ["practice", "advisor", "product_advisor", "account"],
        "plan": {
            "vertex": "phx_dm_pce_account_transfer",
            "filters": [{"field": "to_advisor_sid", "op": "=", "value": ":advisor_sid"}],
            "compute": {"agg": "count", "expr": "*"},
            "trigger": {"op": ">", "value": 0},
            "attribute": None,
            "params": [":advisor_sid"],
            "explanation": "Reads transfer records whose destination is the requested advisor "
                           "and flags each transferred-in account.",
            "unsupported": None,
        },
        "plan_by_scope": {
            "practice": {
                "vertex": "phx_dm_pce_account_transfer",
                "filters": [],
                "compute": {"agg": "count", "expr": "*"},
                "trigger": {"op": ">", "value": 0},
                "attribute": None,
                "params": [],
                "explanation": "At practice scope no advisor filter applies: reads every "
                               "transfer record in the month and flags each account that "
                               "moved between advisors.",
                "unsupported": None,
            },
        },
    },
    {
        "rule_code": "ACCOUNT_TRANSFERRED_OUT",
        "rule_name": "Account Transferred Out",
        "statement": "An account that moved from this advisor to another. Not a lost "
                     "account.",
        "worked_example": "An account reassigned from advisor A to advisor B in May counts as "
                          "transferred out for A and is excluded from A's lost accounts.",
        "kind": "EXCLUDE",
        "grain": "account",
        "driver_tag": "Transfers",
        "evaluation_order": 20,
        # Round G task 1: at practice scope the advisor filter drops — every
        # transferred account is excluded from the firm-wide lost population.
        "scopes": ["practice", "advisor", "product_advisor", "account"],
        "plan": {
            "vertex": "phx_dm_pce_account_transfer",
            "filters": [{"field": "from_advisor_sid", "op": "=", "value": ":advisor_sid"}],
            "compute": {"agg": "count", "expr": "*"},
            "trigger": {"op": ">", "value": 0},
            "attribute": None,
            "params": [":advisor_sid"],
            "explanation": "Reads transfer records whose origin is the requested advisor; "
                           "matched accounts are excluded from the lost-account population.",
            "unsupported": None,
        },
        "plan_by_scope": {
            "practice": {
                "vertex": "phx_dm_pce_account_transfer",
                "filters": [],
                "compute": {"agg": "count", "expr": "*"},
                "trigger": {"op": ">", "value": 0},
                "attribute": None,
                "params": [],
                "explanation": "At practice scope no advisor filter applies: reads every "
                               "transfer record in the month; matched accounts are excluded "
                               "from the firm-wide lost-account population.",
                "unsupported": None,
            },
        },
    },
    {
        "rule_code": "NEW_BILLING",
        "rule_name": "New Billing",
        "statement": "An account that held a balance in the prior month but produced no "
                     "credited revenue, and produced credited revenue this month. Distinct "
                     "from a new account, which did not exist before.",
        "worked_example": "An account with a $50,000 April balance, no April revenue and "
                          "$400 of May revenue is newly billing in May.",
        "kind": "TRIGGER",
        "grain": "account",
        "driver_tag": "New Billing",
        "evaluation_order": 25,
        # Runs AFTER NEW_ACCOUNT (order 10): accounts NEW_ACCOUNT already
        # claimed are excluded — an account opened this month is new, not
        # newly billing.
        "exclude_matched_of": ["NEW_ACCOUNT"],
        "plan": {
            "vertex": "phx_dm_pce_account_month",
            # present_prior_month carries the baseline guard: like LOST_ACCOUNT,
            # this rule cannot fire on 202604 (no prior month exists) and returns
            # empty-with-reason there instead of a fake zero-match.
            "filters": [{"field": "present_prior_month", "op": "=", "value": True},
                        {"field": "prior_end_balance", "op": ">", "value": 0},
                        {"field": "prior_credited_amt", "op": "=", "value": 0},
                        {"field": "credited_amt", "op": ">", "value": 0}],
            "compute": {"agg": "sum", "expr": "credited_amt"},
            "trigger": {"op": ">", "value": 0},
            "attribute": None,
            "params": [],
            "explanation": "Reads account-months that held a prior-month balance with no "
                           "prior-month credited revenue, sums this month's credited "
                           "revenue, and flags accounts that started billing this month.",
            "unsupported": None,
        },
    },
    {
        "rule_code": "LOST_ACCOUNT",
        "rule_name": "Lost Account",
        "statement": "An account whose balance fell to zero, or which had revenue in "
                     "the prior month and none now — and which did not transfer.",
        "worked_example": "An account with April revenue, a zero May balance and no transfer "
                          "record is lost in May.",
        "kind": "TRIGGER",
        "grain": "account",
        "driver_tag": "Lost Accounts",
        "evaluation_order": 30,
        "plan": {
            "vertex": "phx_dm_pce_account_month",
            "filters": [{"field": "is_zero_balance", "op": "=", "value": True},
                        {"field": "present_prior_month", "op": "=", "value": True}],
            # compute reads the PRIOR month's revenue: the population is exactly
            # the rows with zero current revenue (Round C task 0.2 spec fix).
            "compute": {"agg": "sum", "expr": "prior_credited_amt"},
            "trigger": {"op": ">", "value": 0},
            "attribute": None,
            "params": [],
            "explanation": "Reads zero-balance account-months that existed in the prior month, "
                           "sums the prior month's credited revenue, and flags accounts that "
                           "had revenue then and none now.",
            "unsupported": None,
        },
    },
]


def ensure_v0_seed() -> dict:
    """Seed v0 if NO rule-set version exists. Every seed plan passes the same
    five compile checks (incl. execution against mock data) — a broken seed
    fails loudly at startup, never silently."""
    from app.rules.compiler import validate_plan

    store = get_rule_store()
    with _seed_lock:
        existing = store.latest_version(status=None)
        if existing is not None:
            return {"seeded": False, "version_id": existing["version_id"],
                    "rule_count": existing["rule_count"]}
        for rule in V0_RULES:
            plans = {"(default)": rule["plan"],
                     **{f"scope {s}": p for s, p in (rule.get("plan_by_scope") or {}).items()}}
            for label, plan in plans.items():
                outcome = validate_plan(rule["rule_code"], rule["grain"], plan)
                if not outcome["ok"]:
                    raise RuntimeError(f"v0 seed rule {rule['rule_code']} {label} plan "
                                       f"failed validation: {outcome['error']}")
        version = store.create_version(
            0, "PUBLISHED",
            notes="v0 operator-specified seed (ROUND_B_SPEC B3.7, Round E plan format)",
            approved_by="OPERATOR",
        )
        for rule in V0_RULES:
            store.add_rule(
                {
                    **rule,
                    "explanation": rule["plan"].get("explanation"),
                    "provenance": "OPERATOR_SPECIFIED",
                    "status": "PUBLISHED",
                    "confidence": 1.0,
                    "citations": [],
                    "missing": None,
                    "unclear_notes": None,
                },
                version_id=version["version_id"],
            )
        _log.info("seeded v0 rule set: %d rules, version %s",
                  len(V0_RULES), version["version_id"])
        return {"seeded": True, "version_id": version["version_id"],
                "rule_count": len(V0_RULES)}

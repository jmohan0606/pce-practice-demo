"""B3.7 — the v0 operator-specified rule set, seeded at first startup.

Round E shape: each rule is a plain-English ``statement`` plus an
operator-authored ``plan`` in the Rule Compiler's JSON format, validated
through the SAME five checks every compiled rule passes (including execution
against mock data). Provenance OPERATOR_SPECIFIED, evaluation_order
10,20,20,30,40,50; ACCOUNT_TRANSFERRED_OUT evaluates before LOST_ACCOUNT and
transferred accounts are excluded from the lost population.

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
    {
        "rule_code": "FEE_REDUCTION_SHARING",
        "rule_name": "Sharing a Client Fee Discount",
        "statement": "When a client pays more than 10% below the standard fee, the "
                     "advisor's payout grid moves down one point for every 1% below "
                     "that threshold...",
        "worked_example": "115 bps standard, 100 bps actual is a 13% reduction, so the grid "
                          "moves down 3 points.",
        "kind": "TRIGGER",
        "grain": "account",
        "driver_tag": "Fee Rate",
        "evaluation_order": 40,
        "plan": {
            "vertex": "phx_dm_pce_account_month",
            "filters": [{"field": "is_managed", "op": "=", "value": True},
                        {"field": "month_id", "op": "=", "value": ":month"}],
            "compute": {"agg": "none",
                        "expr": "round((standard_rate_bps - client_rate_bps) / standard_rate_bps * 100)"},
            "trigger": {"op": ">", "value": 10},
            "attribute": {"name": "grid_points", "expr": "min(value - 10, 10)"},
            "params": [":month"],
            "explanation": "Reads each managed account-month, computes the percentage the "
                           "client fee sits below standard, and flags those above 10% with "
                           "the grid-point movement capped at 10.",
            "unsupported": None,
        },
    },
    {
        "rule_code": "PARTIAL_PERIOD",
        "rule_name": "Partial Period",
        "statement": "A month with fewer trading days than the one before it will show "
                     "lower revenue for reasons unrelated to the book.",
        "worked_example": "A 19-trading-day month following a 21-day month shows roughly 10% "
                          "less recurring revenue with no change in the book.",
        "kind": "WINDOW",
        "grain": "advisor",
        "driver_tag": "Calendar",
        "evaluation_order": 50,
        "plan": {
            "vertex": "phx_dm_pce_month",
            "filters": [{"field": "is_partial", "op": "=", "value": True}],
            "compute": {"agg": "none", "expr": "trading_days"},
            "trigger": {"op": "<", "value": 21},
            "attribute": None,
            "params": [],
            "explanation": "Reads the month calendar and flags months marked partial whose "
                           "trading-day count is below a full month.",
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
            outcome = validate_plan(rule["rule_code"], rule["grain"], rule["plan"])
            if not outcome["ok"]:
                raise RuntimeError(f"v0 seed rule {rule['rule_code']} failed validation: "
                                   f"{outcome['error']}")
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

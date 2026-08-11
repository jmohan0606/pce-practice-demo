"""B3.7 — the v0 operator-specified rule set, seeded at first startup.

``ensure_v0_seed()`` is idempotent: it creates version RSV_v0 (version_no 0,
status PUBLISHED) with the six B3.7 rules EXACTLY as specified, provenance
OPERATOR_SPECIFIED, evaluation_order 10,20,20,30,40,50 — and does nothing when
any rule-set version already exists.

Wiring: the main thread calls ``app.rules.seed.ensure_v0_seed()`` at startup;
the rules router also invokes it lazily on first /api/rules access, so the API
works even before the startup hook is wired.
"""
from __future__ import annotations

import threading

from app.rules.store import get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.rules.seed")
_seed_lock = threading.Lock()

# The six v0 rules, verbatim from ROUND_B_SPEC.md B3.7 (FEE_REDUCTION_SHARING
# expressions/descriptions verbatim from B3.1). Ordering matters:
# ACCOUNT_TRANSFERRED_OUT (20) evaluates before LOST_ACCOUNT (30) and the
# transferred accounts are excluded from the lost population (evaluator honours
# evaluation_order + exclusion; see app/rules/service.py evaluate_rule_set).
V0_RULES: list[dict] = [
    {
        "rule_code": "NEW_ACCOUNT",
        "rule_name": "New Account",
        "plain_description": "An account opened during the period counts as new for the month "
                             "its first revenue appears.",
        "worked_example": "An account opened in May with $1,200 of May revenue counts as new "
                          "for May.",
        "grain": "account",
        "population": "opened_in_scope = true",
        "compute": "sum(credited_amt)",
        "trigger": "value > 0",
        "attribute": None,
        "driver_tag": "New Accounts",
        "evaluation_order": 10,
    },
    {
        "rule_code": "ACCOUNT_TRANSFERRED_IN",
        "rule_name": "Account Transferred In",
        "plain_description": "An account moved to this advisor from another. Checked before "
                             "lost, so a transfer is never counted as a loss.",
        "worked_example": "An account reassigned from advisor A to advisor B in May counts as "
                          "transferred in for B, not as a new account.",
        "grain": "account",
        "population": "to_advisor_sid = :advisor_sid",
        "compute": "count(*)",
        "trigger": "value > 0",
        "attribute": None,
        "driver_tag": "Transfers",
        "evaluation_order": 20,
    },
    {
        "rule_code": "ACCOUNT_TRANSFERRED_OUT",
        "rule_name": "Account Transferred Out",
        "plain_description": "An account that moved from this advisor to another. Not a lost "
                             "account.",
        "worked_example": "An account reassigned from advisor A to advisor B in May counts as "
                          "transferred out for A and is excluded from A's lost accounts.",
        "grain": "account",
        "population": "from_advisor_sid = :advisor_sid",
        "compute": "count(*)",
        "trigger": "value > 0",
        "attribute": None,
        "driver_tag": "Transfers",
        "evaluation_order": 20,
    },
    {
        "rule_code": "LOST_ACCOUNT",
        "rule_name": "Lost Account",
        "plain_description": "An account whose balance fell to zero, or which had revenue in "
                             "the prior month and none now — and which did not transfer.",
        "worked_example": "An account with April revenue, a zero May balance and no transfer "
                          "record is lost in May.",
        "grain": "account",
        "population": "is_zero_balance = true AND present_prior_month = true",
        "compute": "sum(credited_amt)",
        "trigger": "value > 0",
        "attribute": None,
        "driver_tag": "Lost Accounts",
        "evaluation_order": 30,
    },
    {
        "rule_code": "FEE_REDUCTION_SHARING",
        "rule_name": "Sharing a Client Fee Discount",
        "plain_description": "When a client pays more than 10% below the standard fee, the "
                             "advisor's payout grid moves down one point for every 1% below "
                             "that threshold...",
        "worked_example": "115 bps standard, 100 bps actual is a 13% reduction, so the grid "
                          "moves down 3 points.",
        "grain": "account",
        "population": "is_managed = true AND month_id = :month",
        "compute": "round((standard_rate_bps - client_rate_bps) / standard_rate_bps * 100)",
        "trigger": "value > 10",
        "attribute": "grid_points = min(value - 10, 10)",
        "driver_tag": "Fee Rate",
        "evaluation_order": 40,
    },
    {
        "rule_code": "PARTIAL_PERIOD",
        "rule_name": "Partial Period",
        "plain_description": "A month with fewer trading days than the one before it will show "
                             "lower revenue for reasons unrelated to the book.",
        "worked_example": "A 19-trading-day month following a 21-day month shows roughly 10% "
                          "less recurring revenue with no change in the book.",
        "grain": "advisor",
        "population": "is_partial = true",
        "compute": "trading_days",
        "trigger": "value < 21",
        "attribute": None,
        "driver_tag": "Calendar",
        "evaluation_order": 50,
    },
]


def ensure_v0_seed() -> dict:
    """Seed v0 if NO rule-set version exists. Returns
    {seeded: bool, version_id, rule_count}. Safe to call any number of times,
    from startup and lazily from the rules API."""
    store = get_rule_store()
    with _seed_lock:
        existing = store.latest_version(status=None)
        if existing is not None:
            return {"seeded": False, "version_id": existing["version_id"],
                    "rule_count": existing["rule_count"]}
        version = store.create_version(
            0, "PUBLISHED",
            notes="v0 operator-specified seed (ROUND_B_SPEC B3.7)",
            approved_by="OPERATOR",
        )
        for rule in V0_RULES:
            store.add_rule(
                {
                    **rule,
                    "provenance": "OPERATOR_SPECIFIED",
                    "status": "PUBLISHED",
                    "confidence": 1.0,
                    "citations": [],
                    "unclear_notes": None,
                },
                version_id=version["version_id"],
            )
        _log.info("seeded v0 rule set: %d rules, version %s",
                  len(V0_RULES), version["version_id"])
        return {"seeded": True, "version_id": version["version_id"],
                "rule_count": len(V0_RULES)}

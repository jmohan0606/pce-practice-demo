"""Round A1 task 4 preamble — the ONE place the non-credited reason-code →
cause mapping lives.

The client's 9X codes: small household (9H), inheritance (9G), fee discount
(9D), eligibility (9E). The mock generator emits these codes; the non-credited
analysis queries and the glossary read cause labels and descriptions from HERE.
Real extraction will map the client's actual codes into this table — one edit,
everywhere consistent.

``__NONE__`` marks a credited transaction (no reason code) — it is not a
cause and is deliberately absent from this table.
"""
from __future__ import annotations

# Modelling constants for the 9H (Small Household) cause — one place, imported
# by both the mock generator's 9X post-pass and the non-credited queries so the
# data and its analysis can never disagree.
# HOUSEHOLD_MIN_ASSETS is the mock plan's minimum household asset level: a
# household whose summed account end-balances for the month sit below it does
# not credit. HOUSEHOLD_THRESHOLD_WINDOW feeds
# ``households_within_10k_of_threshold`` — households inside this band below
# the minimum are the ones a consolidation would move into credit.
HOUSEHOLD_MIN_ASSETS = 800_000.0
HOUSEHOLD_THRESHOLD_WINDOW = 10_000.0

# reason_cd -> {cause (stable key for /api/noncredited/detail/{cause}),
#               cause_label, description}
REASON_CODES: dict[str, dict] = {
    "9H": {
        "cause": "household",
        "cause_label": "Small Household",
        "description": "Households below the minimum asset level. Consolidation or a "
                       "household review could bring these into credit.",
    },
    "9G": {
        "cause": "inheritance",
        "cause_label": "Inheritance",
        "description": "Accounts inherited from a departing advisor. Credit follows the "
                       "plan's inheritance window.",
    },
    "9D": {
        "cause": "discount",
        "cause_label": "Fee Discount Applied",
        "description": "Client fee reduced below the standard schedule. Above 10% this "
                       "triggers grid sharing.",
    },
    "9E": {
        "cause": "eligibility",
        "cause_label": "Eligibility",
        "description": "Product or account type outside the credited scope for this "
                       "plan year.",
    },
    # Legacy mock codes (pre-Round-A1 generator output) — kept so historical
    # data renders honestly rather than as "unknown code".
    "ADJ": {
        "cause": "adjustment",
        "cause_label": "Adjustment",
        "description": "A manual adjustment excluded the transaction from credited revenue.",
    },
    "INELG": {
        "cause": "eligibility",
        "cause_label": "Eligibility",
        "description": "Product or account type outside the credited scope for this "
                       "plan year.",
    },
}


def cause_for_code(reason_cd: str | None) -> dict:
    """Mapping row for a reason code — an unknown code comes back labelled as
    exactly that (shown, never dropped, never guessed)."""
    code = str(reason_cd or "").strip()
    if code in REASON_CODES:
        return {"reason_cd": code, **REASON_CODES[code]}
    return {"reason_cd": code, "cause": "unknown",
            "cause_label": f"Unknown Code ({code or 'blank'})",
            "description": "A reason code present in the data but absent from the "
                           "code-to-cause mapping. Shown, never dropped."}

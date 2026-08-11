"""Monthly revenue aggregation: V9 transactions -> V10 phx_dm_pce_monthly_revenue.

Pure functions — no graph, no IO. `mr_id = advisor_sid || '|' || month_id ||
'|' || product_id` (advisor-scoped, the R16 lesson).

"All Advisors" totals are summed at QUERY TIME over these advisor-scoped rows —
this module never emits an all-advisor row, and nothing downstream should
pre-aggregate one (SCHEMA_SPEC §1 V10).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.revenue.products import class_for_group, resolve_product, split_product_id


def _to_float(value) -> float:
    """Numeric or numeric-string amount -> float; blank/None -> 0.0."""
    if value is None:
        return 0.0
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0.0
    return float(value)


def build_monthly_revenue(transactions: Iterable[dict]) -> list[dict]:
    """Aggregate V9 revenue-transaction rows into V10 monthly-revenue rows.

    Input rows carry at least: advisor_sid, month_id, product_id, acct_key,
    credited_amt, non_credited_amt (numeric or numeric strings). group_id, if
    present on the input, is ignored — group and class are re-derived from the
    product_id via resolve_product / class_for_group so the mapping has one
    source of truth.

    Output is deterministic: sorted by mr_id.
    """
    buckets: dict[str, dict] = {}
    for txn in transactions:
        advisor_sid = str(txn["advisor_sid"])
        month_id = str(txn["month_id"])
        product_id = str(txn["product_id"])
        mr_id = f"{advisor_sid}|{month_id}|{product_id}"
        bucket = buckets.get(mr_id)
        if bucket is None:
            product_cd, product_sub_cd = split_product_id(product_id)
            group_id = resolve_product(product_cd, product_sub_cd)
            bucket = buckets[mr_id] = {
                "mr_id": mr_id,
                "advisor_sid": advisor_sid,
                "month_id": month_id,
                "product_id": product_id,
                "group_id": group_id,
                "class_id": class_for_group(group_id),
                "credited_amt": 0.0,
                "non_credited_amt": 0.0,
                "txn_count": 0,
                "_accounts": set(),
            }
        bucket["credited_amt"] += _to_float(txn.get("credited_amt"))
        bucket["non_credited_amt"] += _to_float(txn.get("non_credited_amt"))
        bucket["txn_count"] += 1
        bucket["_accounts"].add(str(txn.get("acct_key", "")))

    rows: list[dict] = []
    for mr_id in sorted(buckets):
        bucket = buckets[mr_id]
        accounts = bucket.pop("_accounts")
        bucket["credited_amt"] = round(bucket["credited_amt"], 2)
        bucket["non_credited_amt"] = round(bucket["non_credited_amt"], 2)
        bucket["distinct_accounts"] = len(accounts)
        rows.append(bucket)
    return rows


def verify_against_transactions(
    transactions: Iterable[dict],
    monthly_rows: Iterable[dict],
    tolerance: float = 0.01,
) -> dict:
    """Independently recompute per-(advisor, month) totals from raw
    transactions and compare against sums over monthly_rows.

    Returns {"ok": bool, "mismatches": [...]}, one mismatch entry per
    (advisor_sid, month_id) whose credited/non-credited totals or txn counts
    disagree beyond `tolerance` (counts must match exactly). Used by the round
    verification script.
    """
    expected: dict[tuple[str, str], dict] = {}
    for txn in transactions:
        key = (str(txn["advisor_sid"]), str(txn["month_id"]))
        agg = expected.setdefault(
            key, {"credited_amt": 0.0, "non_credited_amt": 0.0, "txn_count": 0}
        )
        agg["credited_amt"] += _to_float(txn.get("credited_amt"))
        agg["non_credited_amt"] += _to_float(txn.get("non_credited_amt"))
        agg["txn_count"] += 1

    actual: dict[tuple[str, str], dict] = {}
    for row in monthly_rows:
        key = (str(row["advisor_sid"]), str(row["month_id"]))
        agg = actual.setdefault(
            key, {"credited_amt": 0.0, "non_credited_amt": 0.0, "txn_count": 0}
        )
        agg["credited_amt"] += _to_float(row.get("credited_amt"))
        agg["non_credited_amt"] += _to_float(row.get("non_credited_amt"))
        agg["txn_count"] += int(row.get("txn_count", 0))

    mismatches: list[dict] = []
    for key in sorted(set(expected) | set(actual)):
        exp = expected.get(key, {"credited_amt": 0.0, "non_credited_amt": 0.0, "txn_count": 0})
        act = actual.get(key, {"credited_amt": 0.0, "non_credited_amt": 0.0, "txn_count": 0})
        problems = []
        for amt_field in ("credited_amt", "non_credited_amt"):
            if abs(exp[amt_field] - act[amt_field]) > tolerance:
                problems.append(amt_field)
        if exp["txn_count"] != act["txn_count"]:
            problems.append("txn_count")
        if problems:
            mismatches.append(
                {
                    "advisor_sid": key[0],
                    "month_id": key[1],
                    "fields": problems,
                    "expected": {k: round(v, 2) if isinstance(v, float) else v for k, v in exp.items()},
                    "actual": {k: round(v, 2) if isinstance(v, float) else v for k, v in act.items()},
                }
            )

    return {"ok": not mismatches, "mismatches": mismatches}

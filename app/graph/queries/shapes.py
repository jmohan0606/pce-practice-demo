"""Round 3 task 1 — large-result queries return SHAPES, not rows.

The root fix behind review batch 1 X2/F10/X1: the agent used to be handed a
40-row sample of an arbitrarily large result set and asked to find meaning in
it. Facts were lost, silently. Instead, every catalog query that can return a
large row set now reduces — in CODE, over EVERY row — to a compact shape:
totals, named counts, per-column stats, concentration, outliers, and an
optional ``group_by`` breakdown. Nothing is sampled and nothing is silently
dropped: the counts cover everything; a row list exists only when the caller
explicitly drills (``mode="rows"``), and a drill is 10–20 rows for naming
specifics, never 40 of 50,000.

The shape is computed here, not by the model: free, exact, identical every run.
"""
from __future__ import annotations

from statistics import mean, stdev
from typing import Any

# Per-query shape declarations. ``key``: the row-identity column (named in
# concentration/outlier examples); ``value``: the primary numeric column the
# concentration/outlier analysis runs on; ``flags``: named predicates counted
# over every row (the spec's "with_revenue: 48,201 · zero_balance: 892" form).
SHAPE_SPECS: dict[str, dict] = {
    "accounts_for_month": {
        "key": "acct_key", "value": "credited_amt",
        "flags": {
            "with_revenue": lambda r: _f(r.get("credited_amt")) > 0,
            "zero_balance": lambda r: _truthy(r.get("is_zero_balance")),
        },
    },
    "accounts_opened": {"key": "acct_key", "value": "first_month_revenue", "flags": {}},
    "accounts_zeroed": {"key": "acct_key", "value": "prior_credited_amt", "flags": {}},
    "accounts_absent": {"key": "acct_key", "value": "prior_credited_amt", "flags": {}},
    "transfers_in": {"key": "acct_key", "value": None, "flags": {}},
    "transfers_out": {"key": "acct_key", "value": None, "flags": {}},
    "fee_reduction_accounts": {"key": "acct_key", "value": "reduction_pct", "flags": {}},
    "account_txns": {"key": "txn_id", "value": "credited_amt", "flags": {}},
    "revenue_by_advisor": {"key": "advisor_sid", "value": "credited_amt", "flags": {}},
    "product_advisors": {
        "key": "advisor_sid", "value": "change_amt",
        "flags": {"new_to_product": lambda r: _truthy(r.get("is_new_to_product"))},
    },
    "product_advisor_accounts": {"key": "acct_key", "value": "change_amt", "flags": {}},
    "product_account_txns": {"key": "trade_dt", "value": "credited_amt", "flags": {}},
    "household_accounts": {"key": "acct_key", "value": "credited_amt", "flags": {}},
    "rpg_accounts": {"key": "acct_key", "value": "credited_amt", "flags": {}},
}

# A drill (mode="rows") through an agent tool returns at most this many rows —
# the agent names specifics, it never re-acquires the full set.
DRILL_ROW_CAP = 20

# Groups listed in a group_by breakdown before the remainder rolls into
# "(other)" — a breakdown is itself a shape, never a disguised row list.
GROUP_BREAKDOWN_CAP = 20


def _f(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _numeric_columns(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    return [c for c, v in rows[0].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def compute_shape(query_name: str, rows: list[dict],
                  group_by: str | None = None) -> dict:
    """Reduce a full result set to its shape. Every figure is computed over
    EVERY row — the shape is complete rather than sampled."""
    spec = SHAPE_SPECS.get(query_name) or {"key": None, "value": None, "flags": {}}
    key_col, value_col = spec.get("key"), spec.get("value")
    shape: dict[str, Any] = {"shape_of": query_name, "total_rows": len(rows),
                             "computed_over": "every row — complete, not sampled"}
    if not rows:
        return shape

    # named flag counts
    flags = {label: sum(1 for r in rows if pred(r))
             for label, pred in (spec.get("flags") or {}).items()}
    if flags:
        shape["counts"] = flags

    # per-column stats over every row
    stats: dict[str, dict] = {}
    for col in _numeric_columns(rows):
        values = [_f(r.get(col)) for r in rows]
        stats[col] = {
            "sum": round(sum(values), 2),
            "mean": round(mean(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "nonzero": sum(1 for v in values if v != 0),
        }
    if stats:
        shape["stats"] = stats

    # concentration + outliers on the primary value column
    if value_col and value_col in stats:
        ranked = sorted(rows, key=lambda r: -abs(_f(r.get(value_col))))
        total_abs = sum(abs(_f(r.get(value_col))) for r in rows)
        top10 = ranked[:10]
        top10_abs = sum(abs(_f(r.get(value_col))) for r in top10)
        shape["concentration"] = {
            "top_10_share_pct": (round(top10_abs / total_abs * 100, 1)
                                 if total_abs else None),
            "top_contributors": [
                {key_col or "key": r.get(key_col) if key_col else None,
                 value_col: round(_f(r.get(value_col)), 2)}
                for r in ranked[:5]],
        }
        values = [_f(r.get(value_col)) for r in rows]
        if len(values) >= 3:
            mu = mean(values)
            sigma = stdev(values)
            threshold = mu + 3 * sigma
            outliers = [r for r in rows if _f(r.get(value_col)) > threshold] \
                if sigma else []
            shape["outliers"] = {
                "definition": f"{value_col} > mean + 3 sigma "
                              f"({round(threshold, 2)})",
                "count": len(outliers),
                "keys": [r.get(key_col) for r in outliers[:10]] if key_col else [],
            }

    # optional group_by breakdown — the agent's hypothesis cut
    if group_by:
        if group_by not in rows[0]:
            shape["group_by_error"] = (
                f"column {group_by!r} does not exist on this result — "
                f"columns are {sorted(rows[0])}")
        else:
            grouped: dict[str, dict] = {}
            for r in rows:
                g = grouped.setdefault(str(r.get(group_by)), {"rows": 0, "value_sum": 0.0})
                g["rows"] += 1
                if value_col:
                    g["value_sum"] += _f(r.get(value_col))
            ordered = sorted(grouped.items(), key=lambda kv: -abs(kv[1]["value_sum"]))
            head = ordered[:GROUP_BREAKDOWN_CAP]
            tail = ordered[GROUP_BREAKDOWN_CAP:]
            breakdown = [{group_by: k, "rows": v["rows"],
                          **({"value_sum": round(v["value_sum"], 2)} if value_col else {})}
                         for k, v in head]
            if tail:
                breakdown.append({group_by: f"(other — {len(tail)} more groups)",
                                  "rows": sum(v["rows"] for _, v in tail),
                                  **({"value_sum": round(sum(v["value_sum"] for _, v in tail), 2)}
                                     if value_col else {})})
            shape["group_by"] = {"column": group_by, "groups": breakdown}

    return shape


def shape_capable(query_name: str) -> bool:
    return query_name in SHAPE_SPECS

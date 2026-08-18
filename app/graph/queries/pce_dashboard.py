"""Mock-tier implementations of the B1 dashboard queries.

Each function traverses the FoundationGraphStore exactly the way the installed
GSQL equivalents traverse TigerGraph, and returns the fully shaped payload as
``results[0]`` — routers unwrap and never compute figures themselves.

All figures come from ``phx_dm_pce_monthly_revenue`` (advisor × month × product
grain). ``advisor='all'`` sums across cohort advisors only (``in_cohort=true``).
"""

from __future__ import annotations

from typing import Any

from app.graph.client import mock_query
from app.graph.foundation_store import FoundationGraphStore
from app.shared.reason_codes import UNATTRIBUTED_SID

V_ADVISOR = "phx_dm_pce_advisor"
V_MONTH = "phx_dm_pce_month"
V_MONTHLY_REVENUE = "phx_dm_pce_monthly_revenue"
V_PRODUCT_GROUP = "phx_dm_pce_product_group"
V_REVENUE_CLASS = "phx_dm_pce_revenue_class"

CLASS_ORDER = ["RECURRING", "NON_RECURRING"]  # section order: Recurring, then Non-Recurring


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _advisor_scope(store: FoundationGraphStore, advisor: str) -> set[str]:
    """The advisor SIDs a request aggregates over. 'all' = FIRM scope
    (Round 5): the cohort PLUS the synthetic '__UNATTRIBUTED__' advisor when
    present — firm-wide dashboard totals include unattributed transactions."""
    advisors = store.all_vertices(V_ADVISOR)
    if advisor in ("", "all", None):
        scope = {sid for sid, attrs in advisors.items() if attrs.get("in_cohort") is True}
        if UNATTRIBUTED_SID in advisors:
            scope.add(UNATTRIBUTED_SID)
        return scope
    if advisor not in advisors:
        raise ValueError(f"unknown advisor '{advisor}'")
    return {advisor}


def _is_firm(advisor) -> bool:
    return advisor in ("", "all", None)


def _amt(row: dict[str, Any], firm: bool) -> float:
    """Round 5: firm scope reads firm_credited_amt (the client's dashboard
    filter — reconciles to their PCE report); a single advisor reads
    credited_amt (== advisor_credited_amt). Fallback covers pre-Round-5 rows."""
    if firm:
        v = row.get("firm_credited_amt")
        if v not in (None, ""):
            return _num(v)
    return _num(row.get("credited_amt"))


def _mr_rows(store: FoundationGraphStore, scope: set[str]) -> list[dict[str, Any]]:
    return [
        attrs
        for attrs in store.all_vertices(V_MONTHLY_REVENUE).values()
        if str(attrs.get("advisor_sid")) in scope
    ]


def _months_sorted(store: FoundationGraphStore) -> list[tuple[str, dict[str, Any]]]:
    return sorted(store.all_vertices(V_MONTH).items(), key=lambda kv: kv[0])


def _month_totals(store: FoundationGraphStore, scope: set[str],
                  firm: bool = False) -> list[dict[str, Any]]:
    """Per-month credited totals (with recurring / non-recurring split) over scope."""
    sums: dict[str, dict[str, float]] = {}
    for row in _mr_rows(store, scope):
        month_id = str(row.get("month_id"))
        bucket = sums.setdefault(
            month_id, {"credited": 0.0, "recurring": 0.0, "non_recurring": 0.0, "txn": 0.0}
        )
        credited = _amt(row, firm)
        bucket["credited"] += credited
        if str(row.get("class_id")) == "RECURRING":
            bucket["recurring"] += credited
        else:
            bucket["non_recurring"] += credited
        bucket["txn"] += _num(row.get("txn_count"))

    months: list[dict[str, Any]] = []
    for month_id, attrs in _months_sorted(store):
        bucket = sums.get(month_id, {"credited": 0.0, "recurring": 0.0, "non_recurring": 0.0, "txn": 0.0})
        months.append(
            {
                "month_id": month_id,
                "month_name": attrs.get("month_name"),
                "credited_amt": round(bucket["credited"], 2),
                "recurring_amt": round(bucket["recurring"], 2),
                "non_recurring_amt": round(bucket["non_recurring"], 2),
                "txn_count": int(bucket["txn"]),
                "trading_days": int(_num(attrs.get("trading_days"))),
                "is_baseline": bool(attrs.get("is_baseline")),
                "is_partial": bool(attrs.get("is_partial")),
            }
        )
    return months


@mock_query("pce_dashboard_advisors")
def dashboard_advisors(store: FoundationGraphStore, params: dict) -> list[dict]:
    advisors = [
        {
            "advisor_sid": sid,
            # blank names stay "" — the UI shows the SID; never invent a name
            "advisor_name": attrs.get("advisor_name") or "",
            "in_cohort": attrs.get("in_cohort") is True,
        }
        for sid, attrs in sorted(store.all_vertices(V_ADVISOR).items())
        # Round 5: the synthetic unattributed advisor is a ROW in firm
        # aggregates, never a selectable advisor — you cannot rank or open
        # an advisor that does not exist.
        if sid != UNATTRIBUTED_SID
    ]
    cohort_count = sum(1 for a in advisors if a["in_cohort"])
    return [{"advisors": advisors, "cohort_count": cohort_count}]


@mock_query("pce_dashboard_months")
def dashboard_months(store: FoundationGraphStore, params: dict) -> list[dict]:
    adv = params.get("advisor", "all")
    return [{"months": _month_totals(store, _advisor_scope(store, adv), _is_firm(adv))}]


@mock_query("pce_dashboard_transitions")
def dashboard_transitions(store: FoundationGraphStore, params: dict) -> list[dict]:
    adv = params.get("advisor", "all")
    months = _month_totals(store, _advisor_scope(store, adv), _is_firm(adv))
    transitions: list[dict[str, Any]] = []
    for prev, curr in zip(months, months[1:]):
        from_amt, to_amt = prev["credited_amt"], curr["credited_amt"]
        change_amt = round(to_amt - from_amt, 2)
        change_pct = round(change_amt / from_amt * 100, 2) if from_amt else None
        transitions.append(
            {
                "from_month_id": prev["month_id"],
                "to_month_id": curr["month_id"],
                "from_amt": from_amt,
                "to_amt": to_amt,
                "change_amt": change_amt,
                "change_pct": change_pct,
                "direction": "down" if change_amt < 0 else "up",
                "txn_count": curr["txn_count"],
            }
        )
    return [{"transitions": transitions}]


@mock_query("pce_dashboard_product_contribution")
def dashboard_product_contribution(store: FoundationGraphStore, params: dict) -> list[dict]:
    from_month = str(params.get("from") or "")
    to_month = str(params.get("to") or "")
    month_ids = {mid for mid, _ in _months_sorted(store)}
    for label, mid in (("from", from_month), ("to", to_month)):
        if mid not in month_ids:
            raise ValueError(f"unknown {label} month '{mid}'")

    class_filter = str(params.get("class") or "all")
    if class_filter not in ("all", *CLASS_ORDER):
        raise ValueError(f"unknown class '{class_filter}' (expected all|RECURRING|NON_RECURRING)")

    adv = params.get("advisor", "all")
    scope = _advisor_scope(store, adv)
    firm = _is_firm(adv)
    groups = store.all_vertices(V_PRODUCT_GROUP)
    classes = store.all_vertices(V_REVENUE_CLASS)

    # group_id -> [from_sum, to_sum]; section membership comes from the product
    # group seed, so a group can never appear in two sections.
    sums: dict[str, list[float]] = {}
    for row in _mr_rows(store, scope):
        month_id = str(row.get("month_id"))
        if month_id not in (from_month, to_month):
            continue
        group_id = str(row.get("group_id"))
        bucket = sums.setdefault(group_id, [0.0, 0.0])
        bucket[0 if month_id == from_month else 1] += _amt(row, firm)

    wanted_classes = CLASS_ORDER if class_filter == "all" else [class_filter]
    sections: list[dict[str, Any]] = []
    for class_id in wanted_classes:
        rows: list[dict[str, Any]] = []
        sub_from = sub_to = 0.0
        for group_id, (raw_from, raw_to) in sums.items():
            group = groups.get(group_id, {})
            if (group.get("class_id") or "NON_RECURRING") != class_id:
                continue
            from_amt, to_amt = round(raw_from, 2), round(raw_to, 2)
            if from_amt == 0.0 and to_amt == 0.0:
                # zero in BOTH months is omitted; zero in ONE month is kept —
                # that is a real signal. (unmapped with any amount always renders.)
                continue
            change_amt = round(to_amt - from_amt, 2)
            rows.append(
                {
                    "group_id": group_id,
                    "group_name": group.get("group_name") or group_id,
                    "display_prefix": group.get("display_prefix") or "",
                    "from_amt": from_amt,
                    "to_amt": to_amt,
                    "change_amt": change_amt,
                    "change_pct": round(change_amt / from_amt * 100, 2) if from_amt else None,
                    "direction": "down" if change_amt < 0 else "up",
                }
            )
            sub_from = round(sub_from + from_amt, 2)
            sub_to = round(sub_to + to_amt, 2)
        rows.sort(key=lambda r: r["to_amt"], reverse=True)
        sections.append(
            {
                "class_id": class_id,
                "class_name": classes.get(class_id, {}).get("class_name") or class_id.title(),
                "rows": rows,
                "subtotal": {"from_amt": sub_from, "to_amt": sub_to},
            }
        )

    total_from = round(sum(s["subtotal"]["from_amt"] for s in sections), 2)
    total_to = round(sum(s["subtotal"]["to_amt"] for s in sections), 2)

    def _pcts(entry: dict[str, Any]) -> None:
        change = round(entry["to_amt"] - entry["from_amt"], 2)
        entry["change_amt"] = change
        entry["change_pct"] = round(change / entry["from_amt"] * 100, 2) if entry["from_amt"] else None
        entry["share_pct"] = round(entry["to_amt"] / total_to * 100, 2) if total_to else 0.0

    for section in sections:
        for row in section["rows"]:
            row["share_pct"] = round(row["to_amt"] / total_to * 100, 2) if total_to else 0.0
        _pcts(section["subtotal"])

    total = {"from_amt": total_from, "to_amt": total_to}
    _pcts(total)
    total["share_pct"] = 100.0 if total_to else 0.0

    return [
        {
            "from_month_id": from_month,
            "to_month_id": to_month,
            "sections": sections,
            "total": total,
        }
    ]

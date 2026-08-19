"""Round 3 task 4.1 — driver descriptions that speak to the data.

The old rule-finding summary was the rule definition plus a count ("Rule
NEW_BILLING fired for 17 account(s)…"). This module builds the description
from the MATCHED ROWS themselves — deterministic code over the full match set
(the same material as task 1's shapes): which accounts, how concentrated, at
which advisors, what the small tail contributed. No LLM; identical every run.

This is downstream of task 1 by design — a material fix, not prompt tuning.
"""
from __future__ import annotations

V_AM = "phx_dm_pce_account_month"
V_ADVISOR = "phx_dm_pce_advisor"


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(value: float) -> str:
    return f"(${abs(value):,.0f})" if value < 0 else f"${value:,.0f}"


def _account_advisors(month: str) -> dict[str, str]:
    from app.graph.queries import lookups

    return {str(r.get("acct_key")): str(r.get("advisor_sid"))
            for r in lookups.fetch_vertex_rows(
                V_AM, month=month, columns="acct_key,advisor_sid")}


def _advisor_names() -> dict[str, str]:
    from app.graph.queries import lookups

    return {sid: a.get("advisor_name") or sid
            for sid, a in lookups.advisor_rows(columns="advisor_name").items()}


def dominant_group(matched: list[dict], month: str) -> tuple[str | None, str | None]:
    """Round 3 review F2 — the product group a rule finding belongs to, where
    determinable: the group holding the MAJORITY (>=50%) of the matched
    accounts' credited revenue in the month. (group_id, group_name), or
    (None, None) when no group dominates — attribution is never guessed."""
    from app.graph.queries import lookups

    keys = {str(m.get("key")) for m in matched}
    if not keys:
        return None, None
    group_of = {str(r.get("product_id")): str(r.get("group_id") or "unmapped")
                for r in lookups.fetch_vertex_rows(
                    "phx_dm_pce_product", columns="product_id,group_id")}
    by_group: dict[str, float] = {}
    for r in lookups.fetch_vertex_rows("phx_dm_pce_revenue_transaction",
                                       month=month,
                                       columns="acct_key,product_id,credited_amt"):
        if str(r.get("acct_key")) not in keys:
            continue
        gid = group_of.get(str(r.get("product_id") or ""))
        if gid:
            by_group[gid] = by_group.get(gid, 0.0) + abs(_f(r.get("credited_amt")))
    total = sum(by_group.values())
    if not total:
        return None, None
    gid, amt = max(by_group.items(), key=lambda kv: kv[1])
    if amt / total < 0.5:
        return None, None
    return gid, lookups.product_group_name(gid)


def describe_rule_finding(rule: dict, matched: list[dict], month: str,
                          advisor_sid: str, impact: float | None) -> str:
    """A data-driven description of a rule outcome: totals, concentration,
    advisor attribution, the tail — never the rule definition restated."""
    n = len(matched)
    grain = rule.get("grain") or "entity"
    parts: list[str] = []
    values = [_f(m.get("value")) for m in matched]
    monetary = impact is not None

    head = f"{n} {grain}{'s' if n != 1 else ''} matched in {month}"
    if monetary and impact:
        head += f", totalling {_money(impact)}"
    parts.append(head + ".")

    if monetary and n >= 3 and impact:
        ranked = sorted(matched, key=lambda m: -abs(_f(m.get("value"))))
        top = ranked[:3]
        top_sum = sum(_f(m.get("value")) for m in top)
        share = abs(top_sum) / abs(impact) * 100 if impact else 0
        if share >= 40:
            keys = ", ".join(str(m.get("key")) for m in top)
            parts.append(f"The top {len(top)} ({keys}) account for "
                         f"{_money(top_sum)} of that — {share:.0f}%.")
            tail = ranked[3:]
            if tail:
                tail_max = max(abs(_f(m.get("value"))) for m in tail)
                parts.append(f"The other {len(tail)} contributed under "
                             f"{_money(tail_max if tail_max else 0)} each.")

    # advisor attribution — who the matches sit with (practice-level signal;
    # for a single-advisor run every match is theirs, so say nothing).
    if advisor_sid == "all" and grain == "account" and n:
        owners = _account_advisors(month)
        names = _advisor_names()
        by_advisor: dict[str, int] = {}
        for m in matched:
            sid = owners.get(str(m.get("key")))
            if sid:
                by_advisor[sid] = by_advisor.get(sid, 0) + 1
        if by_advisor:
            ranked_adv = sorted(by_advisor.items(), key=lambda kv: -kv[1])
            top_sid, top_n = ranked_adv[0]
            if len(by_advisor) == 1:
                parts.append(f"All {n} sit with {names.get(top_sid, top_sid)} "
                             f"({top_sid}).")
            elif top_n / n >= 0.5:
                parts.append(f"{top_n} of {n} sit with "
                             f"{names.get(top_sid, top_sid)} ({top_sid}); the "
                             f"rest are spread across "
                             f"{len(by_advisor) - 1} other advisor"
                             f"{'s' if len(by_advisor) > 2 else ''}.")
            else:
                parts.append(f"Spread across {len(by_advisor)} advisors — the "
                             f"largest single share is {top_n} at "
                             f"{names.get(top_sid, top_sid)} ({top_sid}).")

    if not monetary and n and values and any(values):
        vmax, vmin = max(values), min(values)
        if vmax != vmin:
            parts.append(f"Values range {vmin:,.2f} to {vmax:,.2f}.")

    return " ".join(parts)

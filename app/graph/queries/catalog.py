"""C1 — the named, parameterised query catalog the Insights Miner calls.

The Miner NEVER writes GSQL. It chooses a query name and parameters from this
catalog; the query text is fixed and reviewed. Each entry has:

- a typed parameter signature (validated BEFORE execution — a missing required
  parameter fails identically whether or not rows exist, per the task-0 lesson),
- a local implementation against the FoundationGraphStore registered via
  ``@mock_query`` (the tiered client serves it like any catalogued query), and
- a GSQL file under ``docs/tigergraph/queries/<name>.gsql`` with the same name,
  parameters and RETURNS columns.

Conventions (ROUND_C_SPEC C1):
- ``advisor`` accepts an advisor_sid or ``"all"`` (= cohort only, in_cohort=true).
- household traversals include ONLY ``is_owner_role = true`` relationships.
- month ids are "YYYYMM" strings; datetimes are "YYYY-MM-DD HH:MM:SS" strings
  (lexicographically ordered, so range filters are plain string comparisons).

``run_catalog_query(name, params)`` is the single execution entrypoint:
validate → tiered client → ``{"rows": [...], "row_count": n}``.
"""
from __future__ import annotations

from statistics import median
from typing import Any

from app.graph.client import mock_query
from app.graph.foundation_store import FoundationGraphStore
from app.shared.reason_codes import FIRM_REASON_FILTER, UNATTRIBUTED_SID

V_ADVISOR = "phx_dm_pce_advisor"
V_MONTH = "phx_dm_pce_month"
V_MR = "phx_dm_pce_monthly_revenue"
V_GROUP = "phx_dm_pce_product_group"
V_ACCOUNT = "phx_dm_pce_account"
V_AM = "phx_dm_pce_account_month"
V_TXN = "phx_dm_pce_revenue_transaction"
V_TRANSFER = "phx_dm_pce_account_transfer"
V_FLOW = "phx_dm_pce_advisor_flow_month"
V_REL = "phx_dm_pce_account_eci_rel"
V_TEAM = "phx_dm_pce_team_agreement"

FEE_THRESHOLD_DEFAULT = 10.0


class CatalogError(ValueError):
    """Bad query name or parameters — raised BEFORE any rows are fetched."""


def _num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _advisor_scope(store: FoundationGraphStore, advisor: str) -> set[str]:
    advisors = store.all_vertices(V_ADVISOR)
    if advisor in ("", "all", None):
        return {sid for sid, a in advisors.items() if a.get("in_cohort") is True}
    if advisor not in advisors:
        raise CatalogError(f"unknown advisor '{advisor}'")
    return {str(advisor)}


def _firm_scope(store: FoundationGraphStore) -> set[str]:
    """FIRM scope (Round 5): the cohort PLUS the synthetic
    '__UNATTRIBUTED__' advisor when present — firm-wide aggregates include
    unattributed transactions; rankings/peer/drill scopes never do."""
    scope = _advisor_scope(store, "all")
    if UNATTRIBUTED_SID in store.all_vertices(V_ADVISOR):
        scope = scope | {UNATTRIBUTED_SID}
    return scope


def _firm_amt(row: dict) -> float:
    """firm_credited_amt with a fallback to credited_amt for rows from a
    pre-Round-5 store (mock rows all carry the column after the post-pass)."""
    v = row.get("firm_credited_amt")
    return _num(row.get("credited_amt")) if v in (None, "") else _num(v)


def _require_month(store: FoundationGraphStore, month_id: str, label: str = "month_id") -> dict:
    row = store.all_vertices(V_MONTH).get(str(month_id))
    if row is None:
        raise CatalogError(f"unknown {label} '{month_id}'")
    return row


def _mr_rows(store: FoundationGraphStore, scope: set[str], month_id: str | None = None) -> list[dict]:
    return [a for a in store.all_vertices(V_MR).values()
            if str(a.get("advisor_sid")) in scope
            and (month_id is None or str(a.get("month_id")) == str(month_id))]


def _am_rows(store: FoundationGraphStore, scope: set[str], month_id: str | None = None) -> list[dict]:
    return [a for a in store.all_vertices(V_AM).values()
            if str(a.get("advisor_sid")) in scope
            and (month_id is None or str(a.get("month_id")) == str(month_id))]


def _txn_rows(store: FoundationGraphStore, scope: set[str], month_id: str | None = None) -> list[dict]:
    return [a for a in store.all_vertices(V_TXN).values()
            if str(a.get("advisor_sid")) in scope
            and (month_id is None or str(a.get("month_id")) == str(month_id))]


# --------------------------------------------------------------------------- revenue

@mock_query("revenue_by_product")
def revenue_by_product(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    groups = store.all_vertices(V_GROUP)
    out: dict[str, dict] = {}
    for r in _mr_rows(store, scope, params["month_id"]):
        gid = str(r.get("group_id"))
        row = out.setdefault(gid, {
            "group_id": gid,
            "group_name": groups.get(gid, {}).get("group_name") or gid,
            "class_id": str(r.get("class_id")),
            "credited_amt": 0.0, "txn_count": 0, "distinct_accounts": 0,
        })
        row["credited_amt"] = round(row["credited_amt"] + _num(r.get("credited_amt")), 2)
        row["txn_count"] += int(_num(r.get("txn_count")))
        row["distinct_accounts"] += int(_num(r.get("distinct_accounts")))
    return sorted(out.values(), key=lambda r: -r["credited_amt"])


@mock_query("revenue_change_by_product")
def revenue_change_by_product(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    groups = store.all_vertices(V_GROUP)
    sums: dict[str, list[float]] = {}
    for r in _mr_rows(store, scope):
        mid = str(r.get("month_id"))
        if mid not in (frm, to):
            continue
        bucket = sums.setdefault(str(r.get("group_id")), [0.0, 0.0])
        bucket[0 if mid == frm else 1] += _num(r.get("credited_amt"))
    rows = []
    for gid, (a, b) in sums.items():
        from_amt, to_amt = round(a, 2), round(b, 2)
        if from_amt == 0.0 and to_amt == 0.0:
            continue
        change = round(to_amt - from_amt, 2)
        rows.append({
            "group_id": gid,
            "group_name": groups.get(gid, {}).get("group_name") or gid,
            "from_amt": from_amt, "to_amt": to_amt, "change_amt": change,
            "change_pct": round(change / from_amt * 100, 2) if from_amt else None,
        })
    return sorted(rows, key=lambda r: -abs(r["change_amt"]))


@mock_query("revenue_by_advisor")
def revenue_by_advisor(store: FoundationGraphStore, params: dict) -> list[dict]:
    _require_month(store, params["month_id"])
    scope = _advisor_scope(store, "all")  # cohort ranking, in_cohort=true only
    totals = {sid: 0.0 for sid in scope}
    for r in _mr_rows(store, scope, params["month_id"]):
        totals[str(r.get("advisor_sid"))] += _num(r.get("credited_amt"))
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return [{"advisor_sid": sid, "credited_amt": round(amt, 2), "rank": i + 1}
            for i, (sid, amt) in enumerate(ranked)]


@mock_query("advisor_totals")
def advisor_totals(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    from_amt = round(sum(_num(r.get("credited_amt")) for r in _mr_rows(store, scope, frm)), 2)
    to_amt = round(sum(_num(r.get("credited_amt")) for r in _mr_rows(store, scope, to)), 2)
    change = round(to_amt - from_amt, 2)
    return [{"from_amt": from_amt, "to_amt": to_amt, "change_amt": change,
             "change_pct": round(change / from_amt * 100, 2) if from_amt else None}]


# --------------------------------------------------------------------------- accounts

@mock_query("accounts_for_month")
def accounts_for_month(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    return sorted(
        ({"acct_key": str(r.get("acct_key")), "credited_amt": _num(r.get("credited_amt")),
          "end_balance": _num(r.get("end_balance")),
          "is_zero_balance": bool(r.get("is_zero_balance"))}
         for r in _am_rows(store, scope, params["month_id"])),
        key=lambda r: -r["credited_amt"])


@mock_query("accounts_opened")
def accounts_opened(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    from_dt, to_dt = str(params["from_dt"]), str(params["to_dt"])
    # advisor for an account = the advisor(s) holding its account_month rows
    holders: dict[str, set[str]] = {}
    first_rev: dict[str, float] = {}
    for r in sorted(store.all_vertices(V_AM).values(), key=lambda r: str(r.get("month_id"))):
        key = str(r.get("acct_key"))
        holders.setdefault(key, set()).add(str(r.get("advisor_sid")))
        if key not in first_rev and _num(r.get("credited_amt")) > 0:
            first_rev[key] = _num(r.get("credited_amt"))
    rows = []
    for key, acct in store.all_vertices(V_ACCOUNT).items():
        opened = str(acct.get("account_open_dt") or "")
        if not opened or not (from_dt <= opened[:10] <= to_dt[:10] or from_dt <= opened <= to_dt):
            continue
        if not holders.get(key, set()) & scope:
            continue
        rows.append({"acct_key": key, "account_open_dt": opened,
                     "first_month_revenue": round(first_rev.get(key, 0.0), 2)})
    return sorted(rows, key=lambda r: r["account_open_dt"])


@mock_query("accounts_zeroed")
def accounts_zeroed(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, str(params["from_month"]), "from_month")
    _require_month(store, str(params["to_month"]), "to_month")
    rows = []
    for r in _am_rows(store, scope, str(params["to_month"])):
        if bool(r.get("is_zero_balance")) and _num(r.get("prior_end_balance")) > 0:
            rows.append({"acct_key": str(r.get("acct_key")),
                         "prior_balance": _num(r.get("prior_end_balance")),
                         "prior_credited_amt": _num(r.get("prior_credited_amt"))})
    return sorted(rows, key=lambda r: -r["prior_credited_amt"])


@mock_query("accounts_absent")
def accounts_absent(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, str(params["from_month"]), "from_month")
    _require_month(store, str(params["to_month"]), "to_month")
    frm = {str(r.get("acct_key")): r for r in _am_rows(store, scope, str(params["from_month"]))}
    present_to = {str(r.get("acct_key")) for r in _am_rows(store, scope, str(params["to_month"]))}
    return sorted(
        ({"acct_key": key, "prior_credited_amt": _num(row.get("credited_amt"))}
         for key, row in frm.items() if key not in present_to),
        key=lambda r: -r["prior_credited_amt"])


# --------------------------------------------------------------------------- transfers

def _transfers(store: FoundationGraphStore, params: dict, direction: str) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    from_dt, to_dt = str(params["from_dt"]), str(params["to_dt"])
    own_field = "to_advisor_sid" if direction == "in" else "from_advisor_sid"
    other_field = "from_advisor_sid" if direction == "in" else "to_advisor_sid"
    rows = []
    for r in store.all_vertices(V_TRANSFER).values():
        ts = str(r.get("transfer_ts") or "")
        if str(r.get(own_field)) not in scope:
            continue
        if not (from_dt <= ts[:10] <= to_dt[:10] or from_dt <= ts <= to_dt):
            continue
        rows.append({"acct_key": str(r.get("acct_key")),
                     other_field: str(r.get(other_field)), "transfer_ts": ts})
    return sorted(rows, key=lambda r: r["transfer_ts"])


@mock_query("transfers_in")
def transfers_in(store: FoundationGraphStore, params: dict) -> list[dict]:
    return _transfers(store, params, "in")


@mock_query("transfers_out")
def transfers_out(store: FoundationGraphStore, params: dict) -> list[dict]:
    return _transfers(store, params, "out")


# --------------------------------------------------------------------------- fee reduction

def _fee_accounts(store: FoundationGraphStore, scope: set[str], month_id: str) -> dict[str, dict]:
    """Per-account fee-rate facts from the month's rate-bearing transactions."""
    out: dict[str, dict] = {}
    for t in _txn_rows(store, scope, month_id):
        std, cli = _num(t.get("standard_rate_bps")), _num(t.get("client_rate_bps"))
        if std <= 0:
            continue
        key = str(t.get("acct_key"))
        reduction = round((std - cli) / std * 100)
        row = out.setdefault(key, {
            "acct_key": key, "advisor_sid": str(t.get("advisor_sid")),
            "standard_bps": std, "client_bps": cli, "reduction_pct": reduction,
            "grid_reduction": 0.0, "rpg_id": str(t.get("rpg") or ""),
        })
        row["grid_reduction"] = max(row["grid_reduction"], _num(t.get("grid_reduction")))
        row["reduction_pct"] = max(row["reduction_pct"], reduction)
    return out


@mock_query("fee_reduction_accounts")
def fee_reduction_accounts(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    threshold = _num(params.get("threshold_pct", FEE_THRESHOLD_DEFAULT))
    rows = [r for r in _fee_accounts(store, scope, str(params["month_id"])).values()
            if r["reduction_pct"] > threshold]
    return sorted(rows, key=lambda r: -r["reduction_pct"])


@mock_query("fee_reduction_by_rpg")
def fee_reduction_by_rpg(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    by_rpg: dict[str, list[dict]] = {}
    for r in _fee_accounts(store, scope, str(params["month_id"])).values():
        by_rpg.setdefault(r["rpg_id"], []).append(r)
    rows = []
    for rpg_id, accounts in by_rpg.items():
        rows.append({
            "rpg_id": rpg_id, "account_count": len(accounts),
            "blended_reduction_pct": round(
                sum(a["reduction_pct"] for a in accounts) / len(accounts), 2),
            "accounts_above_threshold": sum(
                1 for a in accounts if a["reduction_pct"] > FEE_THRESHOLD_DEFAULT),
        })
    return sorted(rows, key=lambda r: -r["accounts_above_threshold"])


# --------------------------------------------------------------------------- transactions

@mock_query("account_txns")
def account_txns(store: FoundationGraphStore, params: dict) -> list[dict]:
    _require_month(store, params["month_id"])
    acct = str(params["acct_key"])
    rows = [
        {"txn_id": str(t.get("txn_id")), "product_id": str(t.get("product_id")),
         "credited_amt": _num(t.get("credited_amt")), "trade_dt": str(t.get("trade_dt")),
         "reason_cd": "" if str(t.get("reason_cd")) == "__NONE__" else str(t.get("reason_cd"))}
        for t in store.all_vertices(V_TXN).values()
        if str(t.get("acct_key")) == acct and str(t.get("month_id")) == str(params["month_id"])
    ]
    return sorted(rows, key=lambda r: -r["credited_amt"])


def _group_products(store: FoundationGraphStore, group_id: str) -> set[str]:
    products = store.all_vertices("phx_dm_pce_product")
    if group_id not in store.all_vertices(V_GROUP):
        raise CatalogError(f"unknown group_id '{group_id}'")
    return {pid for pid, p in products.items() if str(p.get("group_id")) == group_id}


@mock_query("top_txns")
def top_txns(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    products = _group_products(store, str(params["group_id"]))
    limit = int(_num(params.get("limit", 10)) or 10)
    rows = [
        {"txn_id": str(t.get("txn_id")), "acct_key": str(t.get("acct_key")),
         "credited_amt": _num(t.get("credited_amt")),
         "trade_description": str(t.get("trade_description") or "")}
        for t in _txn_rows(store, scope, str(params["month_id"]))
        if str(t.get("product_id")) in products
    ]
    return sorted(rows, key=lambda r: -r["credited_amt"])[:limit]


@mock_query("product_txn_stats")
def product_txn_stats(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    products = _group_products(store, str(params["group_id"]))
    amounts, accounts = [], set()
    for t in _txn_rows(store, scope, str(params["month_id"])):
        if str(t.get("product_id")) in products:
            amounts.append(_num(t.get("credited_amt")))
            accounts.add(str(t.get("acct_key")))
    return [{"txn_count": len(amounts), "distinct_accounts": len(accounts),
             "avg_amt": round(sum(amounts) / len(amounts), 2) if amounts else 0.0,
             "max_amt": round(max(amounts), 2) if amounts else 0.0}]


@mock_query("non_credited_summary")
def non_credited_summary(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    by_reason: dict[str, dict] = {}
    for t in _txn_rows(store, scope, str(params["month_id"])):
        reason = str(t.get("reason_cd") or "")
        if reason in ("", "__NONE__"):
            continue
        row = by_reason.setdefault(reason, {"reason_cd": reason,
                                            "non_credited_amt": 0.0, "txn_count": 0})
        row["non_credited_amt"] = round(row["non_credited_amt"] + _num(t.get("non_credited_amt")), 2)
        row["txn_count"] += 1
    return sorted(by_reason.values(), key=lambda r: -r["non_credited_amt"])


@mock_query("flows_for_advisor")
def flows_for_advisor(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    return [
        {"flow_product_cd": str(r.get("flow_product_cd")),
         "inflows": _num(r.get("total_inflows")), "outflows": _num(r.get("total_outflows")),
         "net_flows": _num(r.get("total_net_flows")),
         "credited_flows": _num(r.get("credited_flows"))}
        for r in store.all_vertices(V_FLOW).values()
        if str(r.get("advisor_sid")) in scope
        and str(r.get("month_id")) == str(params["month_id"])
    ]


# --------------------------------------------------------------------------- drill-down (Round G task 3)
# Product-scoped queries feeding the four drill-down levels (ROUND_G_SPEC 3.2 /
# ROUND_G_INTERFACE §3). All are practice-wide over the cohort (in_cohort=true)
# — the drill-down starts from the practice contribution table, so there is no
# advisor parameter at the product level.

MOVEMENT_CAUSES_NOTE = "descriptive, not a decomposition"


def _group_txns(store: FoundationGraphStore, group_id: str,
                month_id: str | None = None,
                scope: set[str] | None = None) -> list[dict]:
    products = _group_products(store, group_id)  # validates group_id
    if scope is None:
        scope = _advisor_scope(store, "all")
    return [t for t in store.all_vertices(V_TXN).values()
            if str(t.get("product_id")) in products
            and str(t.get("advisor_sid")) in scope
            and (month_id is None or str(t.get("month_id")) == str(month_id))]


def _sum_credited(txns: list[dict]) -> float:
    return round(sum(_num(t.get("credited_amt")) for t in txns), 2)


def _balances(store: FoundationGraphStore, acct_keys: set[str], month_id: str) -> float:
    """Summed end balances of the given accounts in one month (their AUM)."""
    return round(sum(_num(r.get("end_balance"))
                     for r in store.all_vertices(V_AM).values()
                     if str(r.get("acct_key")) in acct_keys
                     and str(r.get("month_id")) == str(month_id)), 2)


@mock_query("product_transition_metrics")
def product_transition_metrics(store: FoundationGraphStore, params: dict) -> list[dict]:
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    gid = str(params["group_id"])
    # Round 5: this is the PRODUCT level of the drill-down — it must tie to
    # the dashboard contribution row, which is FIRM basis. The advisor rows
    # beneath it (product_advisors) are advisor basis, so this level's total
    # can exceed their sum — correct, and the UI says so (task 14).
    firm = _firm_scope(store)
    frm_txns = _group_txns(store, gid, frm, firm)
    to_txns = _group_txns(store, gid, to, firm)
    frm_accts = {str(t.get("acct_key")) for t in frm_txns}
    to_accts = {str(t.get("acct_key")) for t in to_txns}
    from_amt = round(sum(_firm_amt(t) for t in frm_txns), 2)
    to_amt = round(sum(_firm_amt(t) for t in to_txns), 2)
    return [{
        "from_amt": from_amt, "to_amt": to_amt,
        "change_amt": round(to_amt - from_amt, 2),
        # AUM = end balances of the accounts producing this group's revenue
        "aum": _balances(store, to_accts, to),
        "prior_aum": _balances(store, frm_accts, frm),
        "advisor_count": len({str(t.get("advisor_sid")) for t in to_txns}),
        "prior_advisor_count": len({str(t.get("advisor_sid")) for t in frm_txns}),
        "account_count": len(to_accts),
        "prior_account_count": len(frm_accts),
    }]


@mock_query("product_advisors")
def product_advisors(store: FoundationGraphStore, params: dict) -> list[dict]:
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    gid = str(params["group_id"])
    sums: dict[str, dict] = {}
    for month, slot in ((frm, "from_amt"), (to, "to_amt")):
        for t in _group_txns(store, gid, month):
            sid = str(t.get("advisor_sid"))
            row = sums.setdefault(sid, {
                "advisor_sid": sid, "from_amt": 0.0, "to_amt": 0.0,
                "_from_txns": 0, "_to_accts": set()})
            row[slot] = round(row[slot] + _num(t.get("credited_amt")), 2)
            if month == frm:
                row["_from_txns"] += 1
            else:
                row["_to_accts"].add(str(t.get("acct_key")))
    rows = []
    for row in sums.values():
        rows.append({
            "advisor_sid": row["advisor_sid"],
            "from_amt": row["from_amt"], "to_amt": row["to_amt"],
            "change_amt": round(row["to_amt"] - row["from_amt"], 2),
            "account_count": len(row["_to_accts"]),
            # new to the product = NO revenue rows in this group in from_month
            "is_new_to_product": row["_from_txns"] == 0,
        })
    return sorted(rows, key=lambda r: -abs(r["change_amt"]))


@mock_query("product_advisor_accounts")
def product_advisor_accounts(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    gid = str(params["group_id"])
    sums: dict[str, dict] = {}
    for month, slot in ((frm, "from_amt"), (to, "to_amt")):
        for t in _group_txns(store, gid, month, scope):
            key = str(t.get("acct_key"))
            row = sums.setdefault(key, {"acct_key": key, "from_amt": 0.0,
                                        "to_amt": 0.0, "_to_txns": 0})
            row[slot] = round(row[slot] + _num(t.get("credited_amt")), 2)
            if month == to:
                row["_to_txns"] += 1
    balances = {str(r.get("acct_key")): _num(r.get("end_balance"))
                for r in store.all_vertices(V_AM).values()
                if str(r.get("month_id")) == to}
    rows = []
    for row in sums.values():
        rows.append({
            "acct_key": row["acct_key"],
            "from_amt": row["from_amt"], "to_amt": row["to_amt"],
            "change_amt": round(row["to_amt"] - row["from_amt"], 2),
            "end_balance": balances.get(row["acct_key"], 0.0),
            "txn_count": row["_to_txns"],
        })
    return sorted(rows, key=lambda r: -abs(r["change_amt"]))


@mock_query("product_account_txns")
def product_account_txns(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    acct = str(params["acct_key"])
    rows = [
        {"trade_dt": str(t.get("trade_dt")),
         "trade_description": str(t.get("trade_description") or ""),
         "product_id": str(t.get("product_id")),
         "client_rate_bps": _num(t.get("client_rate_bps")),
         "credited_amt": _num(t.get("credited_amt"))}
        for t in _group_txns(store, str(params["group_id"]),
                             str(params["month_id"]), scope)
        if str(t.get("acct_key")) == acct
    ]
    return sorted(rows, key=lambda r: r["trade_dt"])


@mock_query("product_movement_causes")
def product_movement_causes(store: FoundationGraphStore, params: dict) -> list[dict]:
    """DESCRIPTIVE, not a decomposition — the three effects need not sum to the
    change (ROUND_G_SPEC 3.2; deliberately not V2's attribution model)."""
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    gid = str(params["group_id"])
    frm_txns = _group_txns(store, gid, frm)
    to_txns = _group_txns(store, gid, to)

    def _by(txns: list[dict], field: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for t in txns:
            key = str(t.get(field))
            out[key] = out.get(key, 0.0) + _num(t.get("credited_amt"))
        return out

    adv_from, adv_to = _by(frm_txns, "advisor_sid"), _by(to_txns, "advisor_sid")
    acct_from, acct_to = _by(frm_txns, "acct_key"), _by(to_txns, "acct_key")
    advisor_effect = (sum(v for k, v in adv_to.items() if k not in adv_from)
                      - sum(v for k, v in adv_from.items() if k not in adv_to))
    account_effect = (sum(v for k, v in acct_to.items() if k not in acct_from)
                      - sum(v for k, v in acct_from.items() if k not in acct_to))
    existing = set(acct_from) & set(acct_to)
    rpe_from = (round(sum(acct_from[k] for k in existing) / len(existing), 2)
                if existing else 0.0)
    rpe_to = (round(sum(acct_to[k] for k in existing) / len(existing), 2)
              if existing else 0.0)
    return [{
        "advisor_count_from": len(adv_from), "advisor_count_to": len(adv_to),
        "advisor_effect_amt": round(advisor_effect, 2),
        "account_count_from": len(acct_from), "account_count_to": len(acct_to),
        "account_effect_amt": round(account_effect, 2),
        "rev_per_existing_from": rpe_from, "rev_per_existing_to": rpe_to,
        "rev_per_existing_effect_amt": round((rpe_to - rpe_from) * len(existing), 2),
        "note": MOVEMENT_CAUSES_NOTE,
    }]


# --------------------------------------------------------------------------- dashboard metrics (Round A1 task 3)
# The expanded dashboard table (accounts / trades / revenue per product per
# month with deltas and share) and the chart (AUM per month per product view).
# Metric definitions are app/shared/glossary.METRIC_DEFINITIONS — ONE source,
# served by GET /api/dashboard/definitions, never restated here:
#   accounts = distinct acct_key with credited revenue in the month for that product
#   trades   = count of credited transactions
#   revenue  = sum(firm_credited_amt) under the FIRM reason filter (Round 5)
#   AUM      = sum(end_balance) from account_month for accounts holding that product

PRODUCT_VIEWS = ("all", "split", "recurring", "non_recurring")
_VIEW_CLASS = {"recurring": "RECURRING", "non_recurring": "NON_RECURRING"}
TOTAL_ROW_ID = "__TOTAL__"


def _view_groups(store: FoundationGraphStore, product_view: str) -> dict[str, dict]:
    """The product groups visible in a view. 'all' and 'split' see every group
    (split differs only in presentation); a class view is filtered to its class."""
    view = str(product_view)
    if view not in PRODUCT_VIEWS:
        raise CatalogError(
            f"unknown product_view '{view}' (expected {'|'.join(PRODUCT_VIEWS)})")
    cls = _VIEW_CLASS.get(view)
    return {gid: g for gid, g in store.all_vertices(V_GROUP).items()
            if cls is None or str(g.get("class_id")) == cls}


def _product_group_map(store: FoundationGraphStore) -> dict[str, str]:
    """product_id -> group_id; a product with no group falls to 'unmapped',
    which is shown whenever it has any amount and is never dropped."""
    return {pid: str(p.get("group_id") or "unmapped")
            for pid, p in store.all_vertices("phx_dm_pce_product").items()}


def _credited_txns(store: FoundationGraphStore, month_id: str) -> list[dict]:
    """FIRM-credited transactions (Round 5): rows passing the client's FIRM
    reason filter (NOT IN 9X,XX / blank), cohort + unattributed scope — the
    dashboard reconciles to the client's PCE report, which uses exactly this
    filter. Advisor-level queries use credited_amt (= advisor filter)."""
    scope = _firm_scope(store)
    return [t for t in _txn_rows(store, scope, month_id)
            if FIRM_REASON_FILTER("" if str(t.get("reason_cd")) == "__NONE__"
                                  else str(t.get("reason_cd")))]


def _group_month_metrics(store: FoundationGraphStore, month_id: str,
                         groups: dict[str, dict]) -> dict[str, dict]:
    """gid -> {'accts': set, 'trades': int, 'amt': float, 'advisors': set}
    over the month's credited transactions, restricted to the view's groups."""
    pg = _product_group_map(store)
    out: dict[str, dict] = {}
    for t in _credited_txns(store, month_id):
        gid = pg.get(str(t.get("product_id")), "unmapped")
        if gid not in groups:
            continue
        row = out.setdefault(gid, {"accts": set(), "trades": 0, "amt": 0.0,
                                   "advisors": set()})
        row["accts"].add(str(t.get("acct_key")))
        row["advisors"].add(str(t.get("advisor_sid")))
        row["trades"] += 1
        row["amt"] += _firm_amt(t)  # Round 5: dashboard totals are FIRM basis
    return out


def _group_sort_key(groups: dict[str, dict]):
    def key(gid: str):
        return (int(_num(groups.get(gid, {}).get("sort_order")) or 999), gid)
    return key


@mock_query("product_month_metrics")
def product_month_metrics(store: FoundationGraphStore, params: dict) -> list[dict]:
    month = str(params["month_id"])
    _require_month(store, month)
    groups = _view_groups(store, params["product_view"])
    metrics = _group_month_metrics(store, month, groups)
    rows = []
    for gid in sorted(metrics, key=_group_sort_key(groups)):
        g, m = groups[gid], metrics[gid]
        rows.append({
            "group_id": gid,
            "group_name": str(g.get("group_name") or gid),
            "display_prefix": str(g.get("display_prefix") or ""),
            "class_id": str(g.get("class_id") or ""),
            "account_count": len(m["accts"]),
            "trade_count": m["trades"],
            "credited_amt": round(m["amt"], 2),
        })
    return rows


@mock_query("product_transition_table")
def product_transition_table(store: FoundationGraphStore, params: dict) -> list[dict]:
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    groups = _view_groups(store, params["product_view"])
    m_from = _group_month_metrics(store, frm, groups)
    m_to = _group_month_metrics(store, to, groups)
    active = set(m_from) | set(m_to)  # any activity in either month -> shown, never dropped
    # share_pct is of the FILTERED total (the view's groups only) so the column
    # sums to 100 in every view, including recurring / non_recurring.
    total_to = sum(m["amt"] for m in m_to.values())
    empty = {"accts": set(), "trades": 0, "amt": 0.0}

    def _row(gid: str, f: dict, t: dict, name: str, prefix: str, cls: str) -> dict:
        from_amt, to_amt = round(f["amt"], 2), round(t["amt"], 2)
        change = round(to_amt - from_amt, 2)
        return {
            "group_id": gid, "group_name": name, "display_prefix": prefix,
            "class_id": cls,
            "from_account_count": len(f["accts"]), "from_trade_count": f["trades"],
            "from_amt": from_amt,
            "to_account_count": len(t["accts"]), "to_trade_count": t["trades"],
            "to_amt": to_amt,
            "account_delta": len(t["accts"]) - len(f["accts"]),
            "trade_delta": t["trades"] - f["trades"],
            "change_amt": change,
            # existing decision: change_pct is null when from_amt is 0
            "change_pct": round(change / from_amt * 100, 2) if from_amt else None,
            "share_pct": round(to_amt / total_to * 100, 2) if total_to else 0.0,
            "direction": "up" if change >= 0 else "down",
        }

    rows = [
        _row(gid, m_from.get(gid, empty), m_to.get(gid, empty),
             str(groups[gid].get("group_name") or gid),
             str(groups[gid].get("display_prefix") or ""),
             str(groups[gid].get("class_id") or ""))
        for gid in sorted(active, key=_group_sort_key(groups))
    ]
    # Total row (group_id '__TOTAL__'): revenue/trade totals are sums; account
    # totals are DISTINCT accounts across the view (an account active in two
    # groups counts once here, once per group above).
    all_from = {"accts": set().union(*(m["accts"] for m in m_from.values())) if m_from else set(),
                "trades": sum(m["trades"] for m in m_from.values()),
                "amt": sum(m["amt"] for m in m_from.values())}
    all_to = {"accts": set().union(*(m["accts"] for m in m_to.values())) if m_to else set(),
              "trades": sum(m["trades"] for m in m_to.values()),
              "amt": total_to}
    total = _row(TOTAL_ROW_ID, all_from, all_to, "Total", "", "")
    total["share_pct"] = 100.0 if total_to else 0.0
    rows.append(total)
    return rows


@mock_query("month_aum")
def month_aum(store: FoundationGraphStore, params: dict) -> list[dict]:
    month = str(params["month_id"])
    _require_month(store, month)
    groups = _view_groups(store, params["product_view"])
    metrics = _group_month_metrics(store, month, groups)
    accts: set[str] = set()
    for m in metrics.values():
        accts |= m["accts"]
    # AUM = end balances of the accounts holding the view's products this month
    return [{"month_id": month, "product_view": str(params["product_view"]),
             "aum": _balances(store, accts, month),
             "account_count": len(accts)}]


@mock_query("advisor_count_by_product")
def advisor_count_by_product(store: FoundationGraphStore, params: dict) -> list[dict]:
    month = str(params["month_id"])
    _require_month(store, month)
    gid = str(params["group_id"])
    groups = store.all_vertices(V_GROUP)
    if gid != "all" and gid not in groups:
        raise CatalogError(f"unknown group_id '{gid}'")
    wanted = groups if gid == "all" else {gid: groups[gid]}
    metrics = _group_month_metrics(store, month, wanted)
    advisors: set[str] = set()
    for m in metrics.values():
        advisors |= m["advisors"]
    return [{"group_id": gid, "month_id": month, "advisor_count": len(advisors)}]


LIFECYCLE_RULE_FIELDS = {
    "NEW_ACCOUNT": "new_count",
    "LOST_ACCOUNT": "lost_count",
    "RETAINED_ACCOUNT": "retained_count",
    "ACCOUNT_TRANSFERRED_IN": "transferred_in_count",
    "ACCOUNT_TRANSFERRED_OUT": "transferred_out_count",
}


@mock_query("account_lifecycle_counts")
def account_lifecycle_counts(store: FoundationGraphStore, params: dict) -> list[dict]:
    """New / lost / retained / transferred counts from RULE EVALUATION OUTCOMES
    (evaluate_rule_set — deterministic, honours exclude_matched_of ordering, so
    an account claimed by an earlier rule is never double-counted) plus net
    flows from phx_dm_pce_advisor_flow_month. scope: an advisor_sid, a
    group_id, or 'all' (cohort/practice)."""
    from app.rules.seed import ensure_v0_seed
    from app.rules.service import evaluate_rule_set
    from app.rules.store import get_rule_store

    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    # Lifecycle rules compare to_month against ITS OWN prior month — the query
    # is only honest over consecutive months (or the baseline against itself).
    prior = _prior_month(store, to)
    if prior is None:
        if frm != to:
            raise CatalogError(
                f"to_month {to} is the baseline month — no prior month exists; "
                f"call with from_month == to_month for the baseline position")
    elif frm != prior:
        raise CatalogError(
            f"lifecycle counts are defined over consecutive months: "
            f"from_month must be {prior} for to_month {to}, got '{frm}'")

    scope_id = str(params["scope"])
    advisors = store.all_vertices(V_ADVISOR)
    groups = store.all_vertices(V_GROUP)
    if scope_id in ("", "all"):
        kind, scope_id = "all", "all"
    elif scope_id in advisors:
        kind = "advisor"
    elif scope_id in groups:
        kind = "group"
    else:
        raise CatalogError(
            f"unknown scope '{scope_id}' — expected an advisor_sid, a group_id, or 'all'")

    ensure_v0_seed()
    version = get_rule_store().latest_version("PUBLISHED")
    if version is None:
        raise CatalogError("no PUBLISHED rule-set version exists — seed the rules first")
    outcome = evaluate_rule_set(
        version["version_id"], month=to,
        advisor_sid=scope_id if kind == "advisor" else None)

    group_accts: set[str] | None = None
    if kind == "group":
        wanted = {scope_id: groups[scope_id]}
        group_accts = set()
        for month in (frm, to):
            for m in _group_month_metrics(store, month, wanted).values():
                group_accts |= m["accts"]

    counts = {field: 0 for field in LIFECYCLE_RULE_FIELDS.values()}
    notes: list[str] = []
    for result in outcome["results"]:
        field = LIFECYCLE_RULE_FIELDS.get(str(result.get("rule_code")))
        if field is None:
            continue
        if result.get("empty_reason"):
            notes.append(f"{result['rule_code']}: {result['empty_reason']}")
        # Round 3 review B2 — a SKIPPED lifecycle rule (e.g. deactivated) must
        # never read as a true zero: the note says why the count is absent.
        if result.get("skipped"):
            notes.append(f"{result['rule_code']}: not counted — "
                         f"{result.get('skip_reason') or 'skipped'}")
        keys = {str(entry["key"]) for entry in result.get("matched", [])}
        if group_accts is not None:
            keys &= group_accts
        counts[field] = len(keys)

    # Net flows come from phx_dm_pce_advisor_flow_month — advisor-attributed
    # figures, NOT attributable to a product group; group scope returns null
    # rather than a made-up allocation.
    if kind == "group":
        net_flows = None
        notes.append("net_flows: flow records are advisor-attributed, not "
                     "product-group-attributed — null at group scope")
    else:
        flow_scope = {scope_id} if kind == "advisor" else _advisor_scope(store, "all")
        net_flows = round(sum(_num(r.get("total_net_flows"))
                              for r in store.all_vertices(V_FLOW).values()
                              if str(r.get("advisor_sid")) in flow_scope
                              and str(r.get("month_id")) == to), 2)

    return [{"scope": scope_id, "scope_kind": kind,
             "from_month": frm, "to_month": to,
             **counts, "net_flows": net_flows,
             "rule_set_version": version["version_id"],
             "notes": "; ".join(notes)}]


# --------------------------------------------------------------------------- position (Round E task 4)
# "Where do we stand", not only "what changed". NOTE: advisor_nnm_position was
# DROPPED by operator decision (DECISIONS.md, Round E) — we hold three months of
# net flows against an annual NNM measure, and a proxy must not ship as a fact.
# AUM and net flows ship; NNM waits for real data.

def _prior_month(store: FoundationGraphStore, month_id: str) -> str | None:
    months = sorted(store.all_vertices(V_MONTH))
    idx = months.index(str(month_id))
    return months[idx - 1] if idx > 0 else None


def _aum_totals(store: FoundationGraphStore, scope: set[str], month_id: str) -> dict[str, float]:
    totals = {sid: 0.0 for sid in scope}
    for r in _am_rows(store, scope, month_id):
        totals[str(r.get("advisor_sid"))] += _num(r.get("end_balance"))
    return totals


@mock_query("advisor_aum")
def advisor_aum(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    month = str(params["month_id"])
    _require_month(store, month)
    prior = _prior_month(store, month)
    totals = _aum_totals(store, scope, month)
    prior_totals = _aum_totals(store, scope, prior) if prior else {}
    rows = []
    for sid in scope:
        total = round(totals[sid], 2)
        prior_bal = round(prior_totals[sid], 2) if prior else None
        rows.append({
            "advisor_sid": sid, "month_id": month, "total_balance": total,
            # honest baseline: no prior month held -> null, never 0 or a guess
            "prior_balance": prior_bal,
            "change_amt": round(total - prior_bal, 2) if prior_bal is not None else None,
        })
    return sorted(rows, key=lambda r: -r["total_balance"])


@mock_query("advisor_flows_summary")
def advisor_flows_summary(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    _require_month(store, params["month_id"])
    out: dict[str, dict] = {}
    for r in store.all_vertices(V_FLOW).values():
        sid = str(r.get("advisor_sid"))
        if sid not in scope or str(r.get("month_id")) != str(params["month_id"]):
            continue
        row = out.setdefault(sid, {"advisor_sid": sid, "inflows": 0.0, "outflows": 0.0,
                                   "net_flows": 0.0, "credited_flows": 0.0})
        row["inflows"] = round(row["inflows"] + _num(r.get("total_inflows")), 2)
        row["outflows"] = round(row["outflows"] + _num(r.get("total_outflows")), 2)
        row["net_flows"] = round(row["net_flows"] + _num(r.get("total_net_flows")), 2)
        row["credited_flows"] = round(row["credited_flows"] + _num(r.get("credited_flows")), 2)
    return sorted(out.values(), key=lambda r: -r["net_flows"])


RANKING_METRICS = ("credited_amt", "txn_count", "net_flows", "aum")


@mock_query("cohort_ranking")
def cohort_ranking(store: FoundationGraphStore, params: dict) -> list[dict]:
    _require_month(store, params["month_id"])
    metric = str(params["metric"])
    if metric not in RANKING_METRICS:
        raise CatalogError(
            f"unknown metric '{metric}' (expected {'|'.join(RANKING_METRICS)})")
    advisor = str(params["advisor"])
    cohort = _advisor_scope(store, "all")
    if advisor != "all":
        _advisor_scope(store, advisor)  # existence check
    totals = {sid: 0.0 for sid in cohort}
    if metric == "aum":
        totals = _aum_totals(store, cohort, str(params["month_id"]))
    elif metric == "net_flows":
        for r in store.all_vertices(V_FLOW).values():
            if str(r.get("advisor_sid")) in cohort \
                    and str(r.get("month_id")) == str(params["month_id"]):
                totals[str(r.get("advisor_sid"))] += _num(r.get("total_net_flows"))
    else:
        for r in _mr_rows(store, cohort, params["month_id"]):
            totals[str(r.get("advisor_sid"))] += _num(r.get(metric))
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    med = round(median(totals.values()), 2) if totals else 0.0
    rows = [{"advisor_sid": sid, "metric": metric, "value": round(v, 2),
             "rank": i + 1, "cohort_median": med}
            for i, (sid, v) in enumerate(ranked)]
    if advisor != "all":
        rows = [r for r in rows if r["advisor_sid"] == advisor] or rows
    return rows


@mock_query("advisor_opportunities")
def advisor_opportunities(store: FoundationGraphStore, params: dict) -> list[dict]:
    """Round F2: the real CRM extract shape — grouped by derived stage_group
    (no Won/Lost status exists in the source); forecast amount and actual
    assets stay separate columns, never summed together."""
    scope = _advisor_scope(store, params["advisor"])
    out: dict[tuple, dict] = {}
    for r in store.all_vertices("phx_dm_pce_opportunity").values():
        sid = str(r.get("advisor_sid"))
        if sid not in scope:
            continue
        key = (sid, str(r.get("stage_group") or ""))
        row = out.setdefault(key, {
            "advisor_sid": sid, "stage_group": key[1],
            "forecast_amount": 0.0, "actual_assets": 0.0,
            "opportunity_count": 0, "stalled_count": 0,
            "data_source": str(r.get("data_source") or "CRM"),
        })
        row["forecast_amount"] = round(row["forecast_amount"] + _num(r.get("amount")), 2)
        row["actual_assets"] = round(row["actual_assets"] + _num(r.get("actual_assets")), 2)
        row["opportunity_count"] += 1
        if r.get("is_stalled") in (True, "true"):
            row["stalled_count"] += 1
    return sorted(out.values(), key=lambda r: (r["advisor_sid"], -r["actual_assets"]))


# --------------------------------------------------------------------------- households / rpg / teams

@mock_query("household_accounts")
def household_accounts(store: FoundationGraphStore, params: dict) -> list[dict]:
    eci = str(params["eci_id"])
    # is_owner_role=true ONLY — beneficiary/interested-party links never roll up
    keys = {str(r.get("acct_key")) for r in store.all_vertices(V_REL).values()
            if str(r.get("eci_id")) == eci and bool(r.get("is_owner_role"))}
    latest: dict[str, dict] = {}
    for r in sorted(store.all_vertices(V_AM).values(), key=lambda r: str(r.get("month_id"))):
        if str(r.get("acct_key")) in keys:
            latest[str(r.get("acct_key"))] = r
    return sorted(
        ({"acct_key": k, "advisor_sid": str(r.get("advisor_sid")),
          "credited_amt": _num(r.get("credited_amt"))} for k, r in latest.items()),
        key=lambda r: -r["credited_amt"])


@mock_query("account_household")
def account_household(store: FoundationGraphStore, params: dict) -> list[dict]:
    acct = str(params["acct_key"])
    return [
        {"eci_id": str(r.get("eci_id")),
         "relationship_code": str(r.get("enterprise_relationship_code") or ""),
         "party_role_name": str(r.get("party_role_name") or ""),
         "is_owner_role": bool(r.get("is_owner_role"))}
        for r in store.all_vertices(V_REL).values()
        if str(r.get("acct_key")) == acct
    ]


@mock_query("rpg_accounts")
def rpg_accounts(store: FoundationGraphStore, params: dict) -> list[dict]:
    rpg_id = str(params["rpg_id"])
    if rpg_id not in store.all_vertices("phx_dm_pce_rpg"):
        raise CatalogError(f"unknown rpg_id '{rpg_id}'")
    keys = {edge_from for edge_from, _attrs in
            store.in_index.get("phx_dm_pce_account_in_rpg", {}).get(rpg_id, [])}
    latest: dict[str, dict] = {}
    for r in sorted(store.all_vertices(V_AM).values(), key=lambda r: str(r.get("month_id"))):
        if str(r.get("acct_key")) in keys:
            latest[str(r.get("acct_key"))] = r
    return sorted(
        ({"acct_key": k, "advisor_sid": str(r.get("advisor_sid")),
          "credited_amt": _num(r.get("credited_amt"))} for k, r in latest.items()),
        key=lambda r: -r["credited_amt"])


@mock_query("team_members")
def team_members(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_scope(store, params["advisor"])
    rows = []
    for r in store.all_vertices(V_TEAM).values():
        prm, sec = str(r.get("prm_advisor_sid")), str(r.get("sec_advisor_sid"))
        if not ({prm, sec} & scope):
            continue
        member_is_primary = prm in scope
        rows.append({
            "agreement_id": str(r.get("agreement_id")),
            "prm_advisor_sid": prm, "sec_advisor_sid": sec,
            "share_pct": _num(r.get("prm_share_pct") if member_is_primary
                              else r.get("sec_share_pct")),
            "status": str(r.get("status_cd") or ""),
        })
    return sorted(rows, key=lambda r: r["agreement_id"])


@mock_query("peer_comparison")
def peer_comparison(store: FoundationGraphStore, params: dict) -> list[dict]:
    _require_month(store, params["month_id"])
    metric = str(params["metric"])
    if metric not in ("credited_amt", "txn_count", "net_flows"):
        raise CatalogError(
            f"unknown metric '{metric}' (expected credited_amt|txn_count|net_flows)")
    advisor = str(params["advisor"])
    cohort = _advisor_scope(store, "all")
    if advisor != "all":
        _advisor_scope(store, advisor)  # existence check
    totals = {sid: 0.0 for sid in cohort}
    if metric == "net_flows":
        for r in store.all_vertices(V_FLOW).values():
            if str(r.get("advisor_sid")) in cohort \
                    and str(r.get("month_id")) == str(params["month_id"]):
                totals[str(r.get("advisor_sid"))] += _num(r.get("total_net_flows"))
    else:
        for r in _mr_rows(store, cohort, params["month_id"]):
            totals[str(r.get("advisor_sid"))] += _num(r.get(metric))
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    med = round(median(totals.values()), 2) if totals else 0.0
    rows = [{"advisor_sid": sid, "value": round(v, 2), "rank": i + 1, "cohort_median": med}
            for i, (sid, v) in enumerate(ranked)]
    if advisor != "all":
        rows = [r for r in rows if r["advisor_sid"] == advisor] or rows
    return rows


# --------------------------------------------------------------------------- metadata

@mock_query("month_meta")
def month_meta(store: FoundationGraphStore, params: dict) -> list[dict]:
    row = _require_month(store, params["month_id"])
    return [{"trading_days": int(_num(row.get("trading_days"))),
             "is_baseline": bool(row.get("is_baseline")),
             "is_partial": bool(row.get("is_partial"))}]


@mock_query("account_master")
def account_master(store: FoundationGraphStore, params: dict) -> list[dict]:
    acct = store.all_vertices(V_ACCOUNT).get(str(params["acct_key"]))
    if acct is None:
        raise CatalogError(f"unknown acct_key '{params['acct_key']}'")
    return [{"account_class_cd": str(acct.get("account_class_cd") or ""),
             "managed_platform_cd": str(acct.get("managed_platform_cd") or ""),
             "is_managed": bool(acct.get("is_managed")),
             "opened_in_scope": bool(acct.get("opened_in_scope")),
             "primary_eci_id": str(acct.get("primary_eci_id") or "")}]


# --------------------------------------------------------------------------- the catalog

def _p(name: str, ptype: str, required: bool = True, default: Any = None) -> dict:
    return {"name": name, "type": ptype, "required": required, "default": default}

ADVISOR = _p("advisor", "advisor_sid | 'all'")
MONTH = _p("month_id", "YYYYMM")

CATALOG: dict[str, dict] = {
    "revenue_by_product": {
        "description": "Credited revenue by product group for one month.",
        "params": [ADVISOR, MONTH],
        "returns": ["group_id", "group_name", "class_id", "credited_amt", "txn_count", "distinct_accounts"],
    },
    "revenue_change_by_product": {
        "description": "Product-group revenue change between two months, largest absolute change first.",
        "params": [ADVISOR, _p("from_month", "YYYYMM"), _p("to_month", "YYYYMM")],
        "returns": ["group_id", "group_name", "from_amt", "to_amt", "change_amt", "change_pct"],
    },
    "revenue_by_advisor": {
        "description": "Cohort advisors ranked by credited revenue for one month.",
        "params": [MONTH],
        "returns": ["advisor_sid", "credited_amt", "rank"],
    },
    "advisor_totals": {
        "description": "One advisor's (or the cohort's) total revenue across a transition.",
        "params": [ADVISOR, _p("from_month", "YYYYMM"), _p("to_month", "YYYYMM")],
        "returns": ["from_amt", "to_amt", "change_amt", "change_pct"],
    },
    "accounts_for_month": {
        "description": "Every account-month row for an advisor: revenue, balance, zero flag.",
        "params": [ADVISOR, MONTH],
        "returns": ["acct_key", "credited_amt", "end_balance", "is_zero_balance"],
    },
    "accounts_opened": {
        "description": "Accounts opened in a date range, with their first month of revenue.",
        "params": [ADVISOR, _p("from_dt", "YYYY-MM-DD"), _p("to_dt", "YYYY-MM-DD")],
        "returns": ["acct_key", "account_open_dt", "first_month_revenue"],
    },
    "accounts_zeroed": {
        "description": "Accounts whose balance fell to zero between two months (prior balance/revenue attached).",
        "params": [ADVISOR, _p("from_month", "YYYYMM"), _p("to_month", "YYYYMM")],
        "returns": ["acct_key", "prior_balance", "prior_credited_amt"],
    },
    "accounts_absent": {
        "description": "Accounts present in from_month but with NO row in to_month.",
        "params": [ADVISOR, _p("from_month", "YYYYMM"), _p("to_month", "YYYYMM")],
        "returns": ["acct_key", "prior_credited_amt"],
    },
    "transfers_in": {
        "description": "Accounts transferred TO this advisor in a date range.",
        "params": [ADVISOR, _p("from_dt", "YYYY-MM-DD"), _p("to_dt", "YYYY-MM-DD")],
        "returns": ["acct_key", "from_advisor_sid", "transfer_ts"],
    },
    "transfers_out": {
        "description": "Accounts transferred AWAY from this advisor in a date range.",
        "params": [ADVISOR, _p("from_dt", "YYYY-MM-DD"), _p("to_dt", "YYYY-MM-DD")],
        "returns": ["acct_key", "to_advisor_sid", "transfer_ts"],
    },
    "fee_reduction_accounts": {
        "description": "Accounts whose fee reduction exceeds a threshold, with recorded grid reduction.",
        "params": [ADVISOR, MONTH, _p("threshold_pct", "number", required=False,
                                      default=FEE_THRESHOLD_DEFAULT)],
        "returns": ["acct_key", "advisor_sid", "standard_bps", "client_bps",
                    "reduction_pct", "grid_reduction", "rpg_id"],
    },
    "fee_reduction_by_rpg": {
        "description": "Fee-reduction profile grouped by related-pricing-group.",
        "params": [ADVISOR, MONTH],
        "returns": ["rpg_id", "account_count", "blended_reduction_pct", "accounts_above_threshold"],
    },
    "account_txns": {
        "description": "One account's transactions in a month.",
        "params": [_p("acct_key", "string"), MONTH],
        "returns": ["txn_id", "product_id", "credited_amt", "trade_dt", "reason_cd"],
    },
    "top_txns": {
        "description": "Largest transactions for one product group in a month.",
        "params": [ADVISOR, MONTH, _p("group_id", "string"),
                   _p("limit", "int", required=False, default=10)],
        "returns": ["txn_id", "acct_key", "credited_amt", "trade_description"],
    },
    "product_txn_stats": {
        "description": "Transaction statistics for one product group in a month.",
        "params": [ADVISOR, MONTH, _p("group_id", "string")],
        "returns": ["txn_count", "distinct_accounts", "avg_amt", "max_amt"],
    },
    "non_credited_summary": {
        "description": "Non-credited amounts by reason code for one month.",
        "params": [ADVISOR, MONTH],
        "returns": ["reason_cd", "non_credited_amt", "txn_count"],
    },
    "flows_for_advisor": {
        "description": "Inflows, outflows and net flows by flow product for one month.",
        "params": [ADVISOR, MONTH],
        "returns": ["flow_product_cd", "inflows", "outflows", "net_flows", "credited_flows"],
    },
    "advisor_aum": {
        "description": "AUM position: total end balance per advisor for one month, with the "
                       "prior month's balance and the change (null when no prior month is held).",
        "params": [ADVISOR, MONTH],
        "returns": ["advisor_sid", "month_id", "total_balance", "prior_balance", "change_amt"],
    },
    "advisor_flows_summary": {
        "description": "Flow position per advisor for one month: inflows, outflows, net flows, "
                       "credited flows (summed across flow products).",
        "params": [ADVISOR, MONTH],
        "returns": ["advisor_sid", "inflows", "outflows", "net_flows", "credited_flows"],
    },
    "cohort_ranking": {
        "description": "Cohort ranking on a metric (credited_amt|txn_count|net_flows|aum) for one "
                       "month, with the cohort median; advisor narrows to that advisor's row.",
        "params": [MONTH, _p("metric", "credited_amt|txn_count|net_flows|aum"), ADVISOR],
        "returns": ["advisor_sid", "metric", "value", "rank", "cohort_median"],
    },
    "advisor_opportunities": {
        "description": "CRM pipeline per advisor grouped by stage group (EARLY|MID|LATE|CLOSING) "
                       "with opportunity count, forecast amount, actual assets (separate columns — "
                       "never summed together) and stalled count. Real CRM extract shape; the "
                       "source has NO Won/Lost stage.",
        "params": [ADVISOR],
        "returns": ["advisor_sid", "stage_group", "forecast_amount", "actual_assets",
                    "opportunity_count", "stalled_count", "data_source"],
    },
    "household_accounts": {
        "description": "Accounts of a household (owner-role relationships only), latest-month revenue.",
        "params": [_p("eci_id", "string")],
        "returns": ["acct_key", "advisor_sid", "credited_amt"],
    },
    "account_household": {
        "description": "The household relationships of one account.",
        "params": [_p("acct_key", "string")],
        "returns": ["eci_id", "relationship_code", "party_role_name", "is_owner_role"],
    },
    "rpg_accounts": {
        "description": "Accounts in a related-pricing-group, latest-month revenue.",
        "params": [_p("rpg_id", "string")],
        "returns": ["acct_key", "advisor_sid", "credited_amt"],
    },
    "team_members": {
        "description": "Team agreements this advisor participates in, with their share.",
        "params": [ADVISOR],
        "returns": ["agreement_id", "prm_advisor_sid", "sec_advisor_sid", "share_pct", "status"],
    },
    "peer_comparison": {
        "description": "Cohort ranking on a metric for one month; advisor narrows to that advisor's row.",
        "params": [MONTH, _p("metric", "credited_amt|txn_count|net_flows"), ADVISOR],
        "returns": ["advisor_sid", "value", "rank", "cohort_median"],
    },
    "month_meta": {
        "description": "Trading days, baseline and partial flags for one month.",
        "params": [MONTH],
        "returns": ["trading_days", "is_baseline", "is_partial"],
    },
    "account_master": {
        "description": "One account's master facts (class, platform, managed, opened-in-scope, household).",
        "params": [_p("acct_key", "string")],
        "returns": ["account_class_cd", "managed_platform_cd", "is_managed",
                    "opened_in_scope", "primary_eci_id"],
    },
    # Round G task 3 — drill-down queries (practice-wide, cohort only)
    "product_transition_metrics": {
        "description": "Practice-wide transition metrics for ONE product group: revenue "
                       "from/to/change, AUM of the group's revenue-bearing accounts with "
                       "prior, advisor and account counts with priors.",
        "params": [_p("group_id", "string"), _p("from_month", "YYYYMM"),
                   _p("to_month", "YYYYMM")],
        "returns": ["from_amt", "to_amt", "change_amt", "aum", "prior_aum",
                    "advisor_count", "prior_advisor_count", "account_count",
                    "prior_account_count"],
    },
    "product_advisors": {
        "description": "Every cohort advisor's contribution to one product group across a "
                       "transition; is_new_to_product = no revenue in the group in from_month.",
        "params": [_p("group_id", "string"), _p("from_month", "YYYYMM"),
                   _p("to_month", "YYYYMM")],
        "returns": ["advisor_sid", "from_amt", "to_amt", "change_amt",
                    "account_count", "is_new_to_product"],
    },
    "product_advisor_accounts": {
        "description": "One advisor's accounts in one product group across a transition, "
                       "with to-month end balance and transaction count.",
        "params": [_p("group_id", "string"), ADVISOR, _p("from_month", "YYYYMM"),
                   _p("to_month", "YYYYMM")],
        "returns": ["acct_key", "from_amt", "to_amt", "change_amt",
                    "end_balance", "txn_count"],
    },
    "product_account_txns": {
        "description": "One account's transactions in one product group for one month "
                       "(the drill-down's deterministic floor — no security identifier exists).",
        "params": [_p("group_id", "string"), ADVISOR, _p("acct_key", "string"), MONTH],
        "returns": ["trade_dt", "trade_description", "product_id",
                    "client_rate_bps", "credited_amt"],
    },
    "product_movement_causes": {
        "description": "DESCRIPTIVE movement context for one product group: advisor-count, "
                       "account-count and revenue-per-existing-account deltas with their "
                       "revenue effects. NOT a decomposition — effects need not sum to the "
                       "change (the note column says so).",
        "params": [_p("group_id", "string"), _p("from_month", "YYYYMM"),
                   _p("to_month", "YYYYMM")],
        "returns": ["advisor_count_from", "advisor_count_to", "advisor_effect_amt",
                    "account_count_from", "account_count_to", "account_effect_amt",
                    "rev_per_existing_from", "rev_per_existing_to",
                    "rev_per_existing_effect_amt", "note"],
    },
    # Round A1 task 3 — dashboard metric queries
    "product_month_metrics": {
        "description": "Accounts, trades and credited revenue per product group for one "
                       "month, filtered to the product view (all|split|recurring|"
                       "non_recurring). Metric definitions: GET /api/dashboard/definitions.",
        "params": [MONTH, _p("product_view", "all|split|recurring|non_recurring")],
        "returns": ["group_id", "group_name", "display_prefix", "class_id",
                    "account_count", "trade_count", "credited_amt"],
    },
    "product_transition_table": {
        "description": "Per-group accounts/trades/revenue for both months of a transition "
                       "with deltas and share_pct of the FILTERED to-month total (sums to "
                       "100 in every view). Final row group_id '__TOTAL__': revenue/trade "
                       "sums with DISTINCT account counts across the view.",
        "params": [_p("from_month", "YYYYMM"), _p("to_month", "YYYYMM"),
                   _p("product_view", "all|split|recurring|non_recurring")],
        "returns": ["group_id", "group_name", "display_prefix", "class_id",
                    "from_account_count", "from_trade_count", "from_amt",
                    "to_account_count", "to_trade_count", "to_amt",
                    "account_delta", "trade_delta", "change_amt", "change_pct",
                    "share_pct", "direction"],
    },
    "month_aum": {
        "description": "Total AUM at month end for a product view: summed end balances of "
                       "the accounts with credited revenue in the view's products.",
        "params": [MONTH, _p("product_view", "all|split|recurring|non_recurring")],
        "returns": ["month_id", "product_view", "aum", "account_count"],
    },
    "advisor_count_by_product": {
        "description": "Distinct advisors with credited revenue in one product group "
                       "(group_id 'all' = any group) for one month.",
        "params": [MONTH, _p("group_id", "string")],
        "returns": ["group_id", "month_id", "advisor_count"],
    },
    "account_lifecycle_counts": {
        "description": "New/lost/retained/transferred-in/transferred-out account counts "
                       "from rule evaluation outcomes (deterministic, honours "
                       "exclude_matched_of — no double counting) plus net flows, for an "
                       "advisor_sid, a group_id, or 'all'. Consecutive months only; the "
                       "baseline month reports empty-with-reason rules in notes.",
        "params": [_p("from_month", "YYYYMM"), _p("to_month", "YYYYMM"),
                   _p("scope", "advisor_sid | group_id | 'all'")],
        "returns": ["scope", "scope_kind", "from_month", "to_month", "new_count",
                    "lost_count", "retained_count", "transferred_in_count",
                    "transferred_out_count", "net_flows", "rule_set_version", "notes"],
    },
}


# Round 3 task 1 — shape-capable queries advertise their envelope parameters
# in the agent-facing signature. The three are handled by run_catalog_query
# (popped before the implementation runs); through agent tool layers the
# DEFAULT is mode="shape" — aggregates computed over every row — and a rows
# drill is capped for naming specifics, never re-acquiring the full set.
from app.graph.queries.shapes import (  # noqa: E402
    DRILL_ROW_CAP as _DRILL_ROW_CAP,
    SHAPE_SPECS as _SHAPE_SPECS,
)

for _name in _SHAPE_SPECS:
    if _name in CATALOG:
        CATALOG[_name] = dict(CATALOG[_name])
        CATALOG[_name]["description"] = (
            CATALOG[_name]["description"]
            + " LARGE-RESULT QUERY: by default returns a SHAPE computed over "
              "EVERY row (totals, named counts, per-column stats, top-10 "
              "concentration, >3-sigma outliers) — complete, never sampled. "
              "Pass group_by=<column> for a per-group cut. Pass mode='rows' "
              f"(up to {_DRILL_ROW_CAP} rows) ONLY to name specific rows in a "
              "finding.")
        CATALOG[_name]["params"] = CATALOG[_name]["params"] + [
            _p("mode", "shape|rows — shape is the default and covers every row",
               required=False),
            _p("group_by", "column name for a per-group breakdown (shape mode)",
               required=False),
            _p("limit", f"int <= {_DRILL_ROW_CAP} (rows mode)", required=False),
        ]


def catalog_signatures() -> list[dict]:
    """The catalog as the Miner's get_schema tool serves it."""
    return [{"query_name": name, "description": spec["description"],
             "params": spec["params"], "returns": spec["returns"]}
            for name, spec in CATALOG.items()]


# Round 3 task 1 — envelope parameters handled by run_catalog_query itself,
# never passed to a query implementation. Accepted only on shape-capable
# queries (app/graph/queries/shapes.py).
_ENVELOPE_PARAMS = ("mode", "group_by", "limit")


def validate_params(query_name: str, params: dict) -> dict:
    """Check the query exists and every required parameter is present, BEFORE
    execution. Returns the params with defaults applied. Raises CatalogError."""
    spec = CATALOG.get(query_name)
    if spec is None:
        raise CatalogError(
            f"unknown query '{query_name}' — the catalog has: {', '.join(sorted(CATALOG))}")
    params = dict(params or {})
    unknown = set(params) - {p["name"] for p in spec["params"]}
    if unknown:
        raise CatalogError(
            f"{query_name}: unknown parameter(s) {sorted(unknown)} — "
            f"signature is ({', '.join(p['name'] for p in spec['params'])})")
    for p in spec["params"]:
        if params.get(p["name"]) in (None, ""):
            if p["required"]:
                raise CatalogError(
                    f"{query_name}: required parameter '{p['name']}' ({p['type']}) missing")
            if p["default"] is not None:
                params[p["name"]] = p["default"]
    return params


def run_catalog_query(query_name: str, params: dict | None = None, *,
                      default_mode: str = "rows") -> dict:
    """Validate → tiered graph client → {"rows": [...], "row_count": n}.

    Round 3 task 1 — shape-capable queries (app/graph/queries/shapes.py) accept
    three envelope parameters, handled HERE (the implementations never see
    them):

    - ``mode``: "shape" reduces the FULL result to aggregates computed over
      every row (the agent-facing default — agent tool layers pass
      ``default_mode="shape"``); "rows" returns the row list (API/service
      default, backwards-compatible).
    - ``group_by``: a column name — the shape gains a per-group breakdown.
    - ``limit``: rows mode only — cap the returned list (the full underlying
      rows still ride ``source_rows`` and ``row_count`` stays the full count,
      so nothing is silently dropped).

    Shape-mode results carry ``shape`` plus ``source_rows`` (the complete row
    set) so evidence attached to a finding is every row behind the number.
    """
    from app.graph.client import get_graph_client
    from app.graph.queries.shapes import compute_shape, shape_capable

    params = dict(params or {})
    envelope = {name: params.pop(name, None) for name in _ENVELOPE_PARAMS}
    if any(v not in (None, "") for v in envelope.values()) \
            and not shape_capable(query_name):
        raise CatalogError(
            f"{query_name}: mode/group_by/limit apply only to shape-capable "
            f"queries — this one returns a bounded result already")
    checked = validate_params(query_name, params)
    result = get_graph_client().run_query(query_name, checked)
    rows = result.get("results") or []
    if not shape_capable(query_name):
        return {"rows": rows, "row_count": len(rows)}
    mode = str(envelope.get("mode") or default_mode).lower()
    if mode not in ("shape", "rows"):
        raise CatalogError(f"{query_name}: mode must be 'shape' or 'rows', got {mode!r}")
    if mode == "shape":
        shape = compute_shape(query_name, rows, group_by=envelope.get("group_by") or None)
        return {"rows": [shape], "row_count": len(rows), "shape": shape,
                "source_rows": rows, "mode": "shape"}
    limit = envelope.get("limit")
    shown = rows if limit in (None, "") else rows[:max(0, int(limit))]
    return {"rows": shown, "row_count": len(rows), "source_rows": rows,
            "mode": "rows"}


# ------------------------------------------------------------------- Round F2
# CRM and NNM query extensions live in their own modules (crm_catalog.py owned
# by the CRM workstream, nnm_catalog.py by the NNM workstream) so parallel
# work never edits this file. Each module registers its @mock_query
# implementations on import and contributes catalog entries here. This import
# sits at the END of the module so every shared helper above is available to
# the extension modules.
from app.graph.queries import crm_catalog as _crm_catalog  # noqa: E402
from app.graph.queries import nnm_catalog as _nnm_catalog  # noqa: E402

CATALOG.update(_crm_catalog.EXTRA_CATALOG)
CATALOG.update(_nnm_catalog.EXTRA_CATALOG)

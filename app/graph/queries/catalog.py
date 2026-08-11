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
        "description": "Net-new-money flows by flow product for one month.",
        "params": [ADVISOR, MONTH],
        "returns": ["flow_product_cd", "inflows", "outflows", "net_flows", "credited_flows"],
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
}


def catalog_signatures() -> list[dict]:
    """The catalog as the Miner's get_schema tool serves it."""
    return [{"query_name": name, "description": spec["description"],
             "params": spec["params"], "returns": spec["returns"]}
            for name, spec in CATALOG.items()]


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


def run_catalog_query(query_name: str, params: dict | None = None) -> dict:
    """Validate → tiered graph client → {"rows": [...], "row_count": n}."""
    from app.graph.client import get_graph_client

    checked = validate_params(query_name, params or {})
    result = get_graph_client().run_query(query_name, checked)
    rows = result.get("results") or []
    return {"rows": rows, "row_count": len(rows)}

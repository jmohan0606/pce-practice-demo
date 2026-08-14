"""Round A1 tasks 4+5 — non-credited (9X) analysis and top/bottom advisor
ranking queries. Owned by Subagent B; follows the catalog.py conventions:

- typed parameter signatures validated BEFORE execution (``validate_params``
  mirror — a missing parameter fails identically whether or not rows exist),
- a local implementation against FoundationGraphStore registered via
  ``@mock_query`` so the tiered client serves it like any catalogued query,
- a GSQL file under ``docs/tigergraph/queries/<name>.gsql`` with the same
  name, parameters and RETURNS columns,
- ``run_noncredited_query(name, params)`` as the execution entrypoint:
  validate → tiered client → ``{"rows": [...], "row_count": n}``.

The reason-code → cause mapping lives in app/shared/reason_codes.py — ONE
place; these queries never restate it.

Modelling notes (documented, per-column):
- 9H household assets = sum of the household's account end-balances for the
  queried month; the plan minimum and the ±window come from reason_codes.py
  (the same constants the mock generator's post-pass used, so data and
  analysis cannot disagree).
- 9G ``from_advisor_departed`` is DERIVED, not stored: the source advisor has
  no credited revenue in the queried month. The schema has no departure flag;
  deriving it honestly beats fabricating a field that looks measured.
- 9D grid points expected = one point per 1% of effective reduction above the
  10% threshold (the plan's grid-sharing schedule; threshold from catalog.py's
  FEE_THRESHOLD_DEFAULT). Recorded = the transaction's grid_reduction value.
- 9E groups by PRODUCT, never advisor — eligibility is a plan definition, and
  an advisor grouping would imply blame where there is none.
"""
from __future__ import annotations

from typing import Any

from app.graph.client import mock_query
from app.graph.foundation_store import FoundationGraphStore
from app.graph.queries.catalog import FEE_THRESHOLD_DEFAULT, CatalogError
from app.shared.reason_codes import (HOUSEHOLD_MIN_ASSETS,
                                     HOUSEHOLD_THRESHOLD_WINDOW, REASON_CODES,
                                     cause_for_code)

V_ADVISOR = "phx_dm_pce_advisor"
V_MONTH = "phx_dm_pce_month"
V_ACCOUNT = "phx_dm_pce_account"
V_AM = "phx_dm_pce_account_month"
V_TXN = "phx_dm_pce_revenue_transaction"
V_TRANSFER = "phx_dm_pce_account_transfer"
V_PRODUCT = "phx_dm_pce_product"
V_GROUP = "phx_dm_pce_product_group"

# Rules whose driver measures a STOCK (ongoing revenue), not a flow — they can
# never be "the driver contributing most to the change" and are excluded from
# dominant-driver competition (a concurrent task adds RETAINED_ACCOUNT; a
# 5-rule set simply never hits this).
NON_CHANGE_DRIVERS = {"RETAINED_ACCOUNT"}


def _num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _require_month(store: FoundationGraphStore, month_id: str,
                   label: str = "month_id") -> dict:
    row = store.all_vertices(V_MONTH).get(str(month_id))
    if row is None:
        raise CatalogError(f"unknown {label} '{month_id}'")
    return row


def _cohort(store: FoundationGraphStore) -> set[str]:
    return {sid for sid, a in store.all_vertices(V_ADVISOR).items()
            if a.get("in_cohort") is True}


def _advisor_names(store: FoundationGraphStore) -> dict[str, str]:
    return {sid: str(a.get("advisor_name") or "")
            for sid, a in store.all_vertices(V_ADVISOR).items()}


def _reason_txns(store: FoundationGraphStore, month_id: str,
                 reason_cds: set[str]) -> list[dict]:
    return [t for t in store.all_vertices(V_TXN).values()
            if str(t.get("month_id")) == str(month_id)
            and str(t.get("reason_cd")) in reason_cds]


def _eci_of_acct(store: FoundationGraphStore) -> dict[str, str]:
    return {key: str(a.get("primary_eci_id") or "")
            for key, a in store.all_vertices(V_ACCOUNT).items()}


def _household_assets(store: FoundationGraphStore, month_id: str) -> dict[str, float]:
    """Household assets for one month = sum of member accounts' end balances."""
    eci = _eci_of_acct(store)
    out: dict[str, float] = {}
    for r in store.all_vertices(V_AM).values():
        if str(r.get("month_id")) != str(month_id):
            continue
        hh = eci.get(str(r.get("acct_key")), "")
        out[hh] = out.get(hh, 0.0) + _num(r.get("end_balance"))
    return out


# --------------------------------------------------------------------------- task 4

@mock_query("non_credited_by_cause")
def non_credited_by_cause(store: FoundationGraphStore, params: dict) -> list[dict]:
    _require_month(store, params["month_id"])
    by_code: dict[str, dict] = {}
    for t in _reason_txns(store, str(params["month_id"]),
                          set(REASON_CODES) | {""}):
        code = str(t.get("reason_cd"))
        mapping = cause_for_code(code)
        row = by_code.setdefault(code, {
            "reason_cd": code, "cause": mapping["cause"],
            "cause_label": mapping["cause_label"],
            "description": mapping["description"],
            "_accounts": set(), "_advisors": set(),
            "trade_count": 0, "value": 0.0,
        })
        row["_accounts"].add(str(t.get("acct_key")))
        row["_advisors"].add(str(t.get("advisor_sid")))
        row["trade_count"] += 1
        row["value"] = round(row["value"] + _num(t.get("non_credited_amt")), 2)
    rows = []
    for row in by_code.values():
        rows.append({
            "reason_cd": row["reason_cd"], "cause": row["cause"],
            "cause_label": row["cause_label"], "description": row["description"],
            "account_count": len(row["_accounts"]),
            "trade_count": row["trade_count"], "value": row["value"],
            "advisor_count": len(row["_advisors"]),
        })
    return sorted(rows, key=lambda r: -r["value"])


@mock_query("noncredited_household_detail")
def noncredited_household_detail(store: FoundationGraphStore, params: dict) -> list[dict]:
    month = str(params["month_id"])
    _require_month(store, month)
    eci = _eci_of_acct(store)
    assets = _household_assets(store, month)
    names = _advisor_names(store)
    per: dict[str, dict] = {}
    for t in _reason_txns(store, month, {"9H"}):
        sid = str(t.get("advisor_sid"))
        row = per.setdefault(sid, {"advisor_sid": sid,
                                   "advisor_name": names.get(sid, ""),
                                   "_households": set(), "_accounts": set(),
                                   "trades": 0, "value": 0.0})
        acct = str(t.get("acct_key"))
        row["_accounts"].add(acct)
        row["_households"].add(eci.get(acct, ""))
        row["trades"] += 1
        row["value"] = round(row["value"] + _num(t.get("non_credited_amt")), 2)
    rows = []
    for row in per.values():
        hhs = sorted(row.pop("_households"))
        hh_assets = [assets.get(h, 0.0) for h in hhs]
        row["household_count"] = len(hhs)
        row["accounts"] = len(row.pop("_accounts"))
        row["avg_household_assets"] = (
            round(sum(hh_assets) / len(hh_assets), 2) if hh_assets else 0.0)
        # the households a consolidation would move into credit
        row["households_within_10k_of_threshold"] = sum(
            1 for a in hh_assets
            if HOUSEHOLD_MIN_ASSETS - HOUSEHOLD_THRESHOLD_WINDOW <= a < HOUSEHOLD_MIN_ASSETS)
        rows.append(row)
    return sorted(rows, key=lambda r: -r["value"])


@mock_query("noncredited_inheritance_detail")
def noncredited_inheritance_detail(store: FoundationGraphStore, params: dict) -> list[dict]:
    month = str(params["month_id"])
    _require_month(store, month)
    names = _advisor_names(store)
    # latest transfer per account (mock data has one per inherited account)
    transfer_of: dict[str, dict] = {}
    for tr in sorted(store.all_vertices(V_TRANSFER).values(),
                     key=lambda r: str(r.get("transfer_ts"))):
        transfer_of[str(tr.get("acct_key"))] = tr
    # DERIVED departure flag: the source advisor has no credited revenue in
    # this month (the schema stores no departure field — derive, never invent)
    active = {str(t.get("advisor_sid"))
              for t in store.all_vertices(V_TXN).values()
              if str(t.get("month_id")) == month and _num(t.get("credited_amt")) > 0}

    def months_since(ts: str) -> int:
        y, m = int(ts[:4]), int(ts[5:7])
        return (int(month[:4]) * 12 + int(month[4:6])) - (y * 12 + m)

    per: dict[tuple[str, str], dict] = {}
    for t in _reason_txns(store, month, {"9G"}):
        acct = str(t.get("acct_key"))
        tr = transfer_of.get(acct)
        from_sid = str(tr.get("from_advisor_sid")) if tr else ""
        sid = str(t.get("advisor_sid"))
        ts = str(tr.get("transfer_ts")) if tr else ""
        row = per.setdefault((sid, from_sid), {
            "advisor_sid": sid, "advisor_name": names.get(sid, ""),
            "from_advisor_sid": from_sid,
            "from_advisor_name": names.get(from_sid, ""),
            "from_advisor_departed": from_sid not in active,
            "_accounts": set(),
            "transfer_date": ts[:10],
            "months_since_transfer": months_since(ts) if ts else None,
            "trades": 0, "value": 0.0,
        })
        row["_accounts"].add(acct)
        row["trades"] += 1
        row["value"] = round(row["value"] + _num(t.get("non_credited_amt")), 2)
    rows = []
    for row in per.values():
        row["accounts"] = len(row.pop("_accounts"))
        rows.append(row)
    return sorted(rows, key=lambda r: -r["value"])


@mock_query("noncredited_discount_detail")
def noncredited_discount_detail(store: FoundationGraphStore, params: dict) -> list[dict]:
    month = str(params["month_id"])
    _require_month(store, month)
    names = _advisor_names(store)
    # per-account fee facts from the month's 9D rows
    accts: dict[str, dict] = {}
    for t in _reason_txns(store, month, {"9D"}):
        key = str(t.get("acct_key"))
        red = _num(t.get("eff_disc_pct"))
        row = accts.setdefault(key, {
            "advisor_sid": str(t.get("advisor_sid")),
            "std": _num(t.get("standard_rate_bps")),
            "cli": _num(t.get("client_rate_bps")),
            "reduction": red, "grid_recorded": 0.0, "value": 0.0,
        })
        row["reduction"] = max(row["reduction"], red)
        row["grid_recorded"] = max(row["grid_recorded"], _num(t.get("grid_reduction")))
        row["value"] = round(row["value"] + _num(t.get("non_credited_amt")), 2)
    per: dict[str, dict] = {}
    for facts in accts.values():
        sid = facts["advisor_sid"]
        row = per.setdefault(sid, {"advisor_sid": sid,
                                   "advisor_name": names.get(sid, ""),
                                   "_accts": [], "trades": 0, "value": 0.0})
        row["_accts"].append(facts)
        row["value"] = round(row["value"] + facts["value"], 2)
    for t in _reason_txns(store, month, {"9D"}):
        per[str(t.get("advisor_sid"))]["trades"] += 1
    rows = []
    for row in per.values():
        group = row.pop("_accts")
        n = len(group)
        above = [a for a in group if a["reduction"] > FEE_THRESHOLD_DEFAULT]
        rows.append({
            "advisor_sid": row["advisor_sid"], "advisor_name": row["advisor_name"],
            "accounts": n,
            "avg_standard_bps": round(sum(a["std"] for a in group) / n, 1),
            "avg_actual_bps": round(sum(a["cli"] for a in group) / n, 1),
            "avg_reduction_pct": round(sum(a["reduction"] for a in group) / n, 1),
            "accounts_above_10pct": len(above),
            # one grid point per 1% of effective reduction above the threshold
            "grid_points_expected": sum(
                int(round(a["reduction"] - FEE_THRESHOLD_DEFAULT)) for a in above),
            "grid_points_recorded": sum(
                int(round(a["grid_recorded"])) for a in group),
            "value": row["value"],
        })
    return sorted(rows, key=lambda r: -r["value"])


@mock_query("noncredited_eligibility_detail")
def noncredited_eligibility_detail(store: FoundationGraphStore, params: dict) -> list[dict]:
    """Grouped by PRODUCT, not advisor — eligibility is a plan definition,
    not advisor behaviour; an advisor grouping would imply blame."""
    month = str(params["month_id"])
    _require_month(store, month)
    products = store.all_vertices(V_PRODUCT)
    per: dict[str, dict] = {}
    # legacy INELG maps to the same eligibility cause — include it so historic
    # data renders honestly (reason_codes.py is the one mapping)
    codes = {c for c, m in REASON_CODES.items() if m["cause"] == "eligibility"}
    for t in _reason_txns(store, month, codes):
        pid = str(t.get("product_id"))
        p = products.get(pid, {})
        gid = str(p.get("group_id") or "unmapped")
        row = per.setdefault(pid, {
            "product_id": pid,
            "product": str(p.get("product_name") or pid),
            "group_id": gid,
            "reason": ("Product code absent from the product mapping"
                       if gid == "unmapped"
                       else "Product outside the credited scope for this plan year"),
            "_accounts": set(), "_advisors": set(), "trades": 0, "value": 0.0,
        })
        row["_accounts"].add(str(t.get("acct_key")))
        row["_advisors"].add(str(t.get("advisor_sid")))
        row["trades"] += 1
        row["value"] = round(row["value"] + _num(t.get("non_credited_amt")), 2)
    rows = []
    for row in per.values():
        rows.append({
            "product_id": row["product_id"], "product": row["product"],
            "group_id": row["group_id"], "reason": row["reason"],
            "accounts": len(row["_accounts"]),
            "advisors": len(row["_advisors"]),
            "trades": row["trades"], "value": row["value"],
        })
    return sorted(rows, key=lambda r: -r["value"])


# --------------------------------------------------------------------------- task 5

def _group_products(store: FoundationGraphStore, group_id: str) -> set[str]:
    if group_id not in store.all_vertices(V_GROUP):
        raise CatalogError(f"unknown group_id '{group_id}'")
    return {pid for pid, p in store.all_vertices(V_PRODUCT).items()
            if str(p.get("group_id")) == group_id}


def _dominant_drivers(store: FoundationGraphStore, month: str,
                      sids: list[str],
                      group_accounts: dict[str, set[str]]) -> dict[str, str | None]:
    """dominant_driver_code per advisor, DETERMINISTICALLY from rule
    evaluation outcomes (evaluate_rule_set at advisor scope): the driver whose
    rules' monetary impact over this advisor's accounts IN THIS PRODUCT GROUP
    is largest in absolute value. No outcome → None. NEVER guessed."""
    from app.insights.service import _monetary_impact
    from app.rules.seed import ensure_v0_seed
    from app.rules.service import evaluate_rule_set
    from app.rules.store import get_rule_store

    ensure_v0_seed()
    version = get_rule_store().latest_version("PUBLISHED")
    if version is None:
        return {sid: None for sid in sids}
    rule_map = {r["rule_key"]: r
                for r in get_rule_store().version_rules(version["version_id"])}
    out: dict[str, str | None] = {}
    for sid in sids:
        impacts: dict[str, float] = {}
        outcome = evaluate_rule_set(version["version_id"], month=month,
                                    advisor_sid=sid, scope="advisor")
        for result in outcome["results"]:
            if not result.get("evaluated"):
                continue
            rule = rule_map.get(result.get("rule_key")) or {}
            code = str(rule.get("driver_code") or "")
            if not code or code in NON_CHANGE_DRIVERS:
                continue
            # restrict matched keys to accounts active in this product group
            # for this advisor (matched key = acct_key for account-grain rules;
            # composite keys carry the account first)
            matched = [m for m in result.get("matched") or []
                       if str(m.get("key", "")).split("|")[0]
                       in group_accounts.get(sid, set())]
            if not matched:
                continue
            impact = _monetary_impact(rule, matched)
            if impact is None:
                continue
            impacts[code] = round(impacts.get(code, 0.0) + impact, 2)
        if impacts:
            # deterministic tie-break: |impact| desc, then driver_code asc
            out[sid] = sorted(impacts.items(),
                              key=lambda kv: (-abs(kv[1]), kv[0]))[0][0]
        else:
            out[sid] = None  # no rule outcome — the UI says "not generated yet"
    return out


@mock_query("product_advisor_ranking")
def product_advisor_ranking(store: FoundationGraphStore, params: dict) -> list[dict]:
    frm, to = str(params["from_month"]), str(params["to_month"])
    _require_month(store, frm, "from_month")
    _require_month(store, to, "to_month")
    gid = str(params["group_id"])
    products = _group_products(store, gid)
    limit = int(_num(params.get("limit", 10)) or 10)
    names = _advisor_names(store)
    cohort = _cohort(store)

    sums: dict[str, dict] = {}
    group_accounts: dict[str, set[str]] = {}
    for t in store.all_vertices(V_TXN).values():
        sid = str(t.get("advisor_sid"))
        mid = str(t.get("month_id"))
        if str(t.get("product_id")) not in products or sid not in cohort \
                or mid not in (frm, to) or _num(t.get("credited_amt")) <= 0:
            continue
        row = sums.setdefault(sid, {"advisor_sid": sid, "from_amt": 0.0,
                                    "to_amt": 0.0, "_from_accts": set(),
                                    "_to_accts": set()})
        slot = "from_amt" if mid == frm else "to_amt"
        row[slot] = round(row[slot] + _num(t.get("credited_amt")), 2)
        row["_from_accts" if mid == frm else "_to_accts"].add(str(t.get("acct_key")))
        group_accounts.setdefault(sid, set()).add(str(t.get("acct_key")))

    total_change = round(sum(r["to_amt"] - r["from_amt"] for r in sums.values()), 2)
    ranked = sorted(sums.values(),
                    key=lambda r: (-(r["to_amt"] - r["from_amt"]), r["advisor_sid"]))
    n = len(ranked)
    top_sids = {r["advisor_sid"] for r in ranked[:min(limit, n)]}
    bottom_sids = {r["advisor_sid"] for r in ranked[max(0, n - limit):]}
    keep = [r for r in ranked if r["advisor_sid"] in top_sids | bottom_sids]
    dominant = _dominant_drivers(store, to, [r["advisor_sid"] for r in keep],
                                 group_accounts)
    rows = []
    for r in keep:
        change = round(r["to_amt"] - r["from_amt"], 2)
        in_top, in_bottom = r["advisor_sid"] in top_sids, r["advisor_sid"] in bottom_sids
        rows.append({
            "advisor_sid": r["advisor_sid"],
            # blank name stays blank — the UI falls back to the SID alone
            "advisor_name": names.get(r["advisor_sid"], ""),
            "from_amt": r["from_amt"], "to_amt": r["to_amt"],
            "change_amt": change,
            "change_pct": (round(change / r["from_amt"] * 100, 2)
                           if r["from_amt"] else None),
            "pct_of_total_change": (round(change / total_change * 100, 2)
                                    if total_change else None),
            "account_count": len(r["_to_accts"]),
            "account_delta": len(r["_to_accts"]) - len(r["_from_accts"]),
            "dominant_driver_code": dominant.get(r["advisor_sid"]),
            "side": "both" if in_top and in_bottom else ("top" if in_top else "bottom"),
            # over ALL advisors in the group, not only the kept top/bottom rows
            "group_total_change_amt": total_change,
            "group_advisor_count": n,
        })
    return rows  # ordered by change_amt desc; router splits top/bottom by side


# --------------------------------------------------------------------------- the catalog

def _p(name: str, ptype: str, required: bool = True, default: Any = None) -> dict:
    return {"name": name, "type": ptype, "required": required, "default": default}

MONTH = _p("month_id", "YYYYMM")

NONCREDITED_CATALOG: dict[str, dict] = {
    "non_credited_by_cause": {
        "description": "Non-credited transactions grouped by reason code / cause for one "
                       "month: accounts, trades, value, advisors (cohort-wide).",
        "params": [MONTH],
        "returns": ["reason_cd", "cause", "cause_label", "description",
                    "account_count", "trade_count", "value", "advisor_count"],
    },
    "noncredited_household_detail": {
        "description": "9H Small Household detail per advisor; "
                       "households_within_10k_of_threshold names the households a "
                       "consolidation would move into credit.",
        "params": [MONTH],
        "returns": ["advisor_sid", "advisor_name", "household_count", "accounts",
                    "trades", "value", "avg_household_assets",
                    "households_within_10k_of_threshold"],
    },
    "noncredited_inheritance_detail": {
        "description": "9G Inheritance detail per (receiving advisor, source advisor); "
                       "months_since_transfer drives the six-month departure exception; "
                       "from_advisor_departed is derived (no credited revenue this month).",
        "params": [MONTH],
        "returns": ["advisor_sid", "advisor_name", "from_advisor_sid",
                    "from_advisor_name", "from_advisor_departed", "accounts",
                    "transfer_date", "months_since_transfer", "trades", "value"],
    },
    "noncredited_discount_detail": {
        "description": "9D Fee Discount detail per advisor; grid_points_expected vs "
                       "recorded is the expected-vs-recorded gap (one point per 1% above "
                       "the 10% threshold).",
        "params": [MONTH],
        "returns": ["advisor_sid", "advisor_name", "accounts", "avg_standard_bps",
                    "avg_actual_bps", "avg_reduction_pct", "accounts_above_10pct",
                    "grid_points_expected", "grid_points_recorded", "value"],
    },
    "noncredited_eligibility_detail": {
        "description": "9E Eligibility detail grouped by PRODUCT (a plan definition, not "
                       "advisor behaviour) — includes legacy INELG rows.",
        "params": [MONTH],
        "returns": ["product_id", "product", "group_id", "reason", "accounts",
                    "advisors", "trades", "value"],
    },
    "product_advisor_ranking": {
        "description": "Top N and bottom N cohort advisors for one product group across a "
                       "transition, ranked by change amount, with pct_of_total_change and "
                       "a deterministic dominant_driver_code from rule outcomes (null when "
                       "no rule outcome exists — never guessed).",
        "params": [_p("from_month", "YYYYMM"), _p("to_month", "YYYYMM"),
                   _p("group_id", "string"),
                   _p("limit", "int", required=False, default=10)],
        "returns": ["advisor_sid", "advisor_name", "from_amt", "to_amt", "change_amt",
                    "change_pct", "pct_of_total_change", "account_count",
                    "account_delta", "dominant_driver_code", "side",
                    "group_total_change_amt", "group_advisor_count"],
    },
}


def validate_params(query_name: str, params: dict) -> dict:
    """Same contract as catalog.validate_params, over this module's catalog."""
    spec = NONCREDITED_CATALOG.get(query_name)
    if spec is None:
        raise CatalogError(f"unknown query '{query_name}' — this module has: "
                           f"{', '.join(sorted(NONCREDITED_CATALOG))}")
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


def run_noncredited_query(query_name: str, params: dict | None = None) -> dict:
    """Validate → tiered graph client → {"rows": [...], "row_count": n}."""
    from app.graph.client import get_graph_client

    checked = validate_params(query_name, params or {})
    result = get_graph_client().run_query(query_name, checked)
    rows = result.get("results") or []
    return {"rows": rows, "row_count": len(rows)}

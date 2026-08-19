"""Round 3 task 3 — the exceptions model: rates, not counts.

An absolute threshold punishes size: an advisor with 500 accounts and 12 above
a threshold is at 2.4%; one with 30 accounts and 8 above is at 26.7%. Ranking
by count sends someone to a conversation that is not warranted. This module
computes, for every PUBLISHED + active + ``exception_enabled`` rule:

    affected / denominator   vs   the cohort distribution on that same rate

using the eight exception-configuration fields Round 1 put on the rule vertex:

- ``exception_denominator`` — what the rate is measured against. Resolution is
  by the field's own language: text naming *revenue* measures dollars against
  prior-month credited revenue (losing 3 accounts worth $40k matters more than
  20 worth $2k); text naming *managed* counts managed accounts; anything else
  (null included) counts the advisor's accounts in the month, and the label
  says which was used.
- ``product_scope`` — narrows the denominator population (8 of 30 *managed*
  accounts is 26.7%, not 8 of 500 at 1.6%). The scope comes from the plan's
  own extracted language; scope text naming the managed fee schedule resolves
  to managed accounts. The cohort narrows with it: the comparison population
  is advisors WITH a non-empty in-scope denominator, so advisors who do not
  sell the product never drag the median down.
- ``exception_floor`` (+``exception_floor_unit``) — suppresses noise: a
  2-of-8 advisor at 25% would top every ranking while meaning nothing.
  Unit "accounts" (default) floors the affected count; "dollars" floors the
  affected amount.
- ``exception_sensitivity`` — replaces an invented threshold: an advisor is
  flagged when their rate sits materially above the cohort distribution —
  rate > cohort median + sensitivity × cohort standard deviation (in-scope
  advisors only). Null defaults to 1.0, stated on the output.

``driver_enabled`` and ``exception_enabled`` are independent (task 3.3): a
rule can explain a movement (driver) without being a problem (exception), and
vice versa — one toggle would force losing the explanation to remove the
noise.
"""
from __future__ import annotations

from statistics import median, stdev

from app.shared.logging import get_logger

_log = get_logger("app.insights.exceptions")

DEFAULT_SENSITIVITY = 1.0

V_AM = "phx_dm_pce_account_month"
V_ACCOUNT = "phx_dm_pce_account"
V_ADVISOR = "phx_dm_pce_advisor"
V_MONTH = "phx_dm_pce_month"


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _prior_month(month: str) -> str | None:
    from app.graph.queries import lookups

    months = lookups.month_ids()
    try:
        idx = months.index(str(month))
    except ValueError:
        return None
    return months[idx - 1] if idx > 0 else None


def _scope_is_managed(product_scope: str | None) -> bool:
    """Scope text naming the managed platform / managed fee schedule narrows
    to managed accounts. The scope is extracted plan language, not config —
    unrecognised text applies no narrowing (stated on the output rather than
    guessed)."""
    text = (product_scope or "").lower()
    return "managed" in text or "145" in text


def _denominator_kind(rule: dict) -> tuple[str, str]:
    """(kind, label). kind: 'revenue' (dollar-weighted, prior-month credited
    revenue), 'managed_accounts', or 'accounts'."""
    text = (rule.get("exception_denominator") or "").lower()
    scoped_managed = _scope_is_managed(rule.get("product_scope"))
    if "revenue" in text:
        return "revenue", "prior-month credited revenue"
    if "managed" in text or scoped_managed:
        return "managed_accounts", "managed accounts"
    return "accounts", "accounts in month"


def _advisor_accounts(month: str) -> dict[str, list[dict]]:
    """advisor_sid -> that advisor's account_month rows for the month, with
    the account master's is_managed merged on."""
    from app.graph.queries import lookups

    managed = lookups.account_managed_map()
    out: dict[str, list[dict]] = {}
    for row in lookups.fetch_vertex_rows(
            V_AM, month=month, columns="acct_key,advisor_sid,credited_amt"):
        r = dict(row)
        r["is_managed"] = managed.get(str(row.get("acct_key")), False)
        out.setdefault(str(row.get("advisor_sid")), []).append(r)
    return out


def _cohort_sids() -> list[str]:
    from app.graph.queries import lookups

    return lookups.cohort_sids()


def _advisor_names() -> dict[str, str]:
    from app.graph.queries import lookups

    return {sid: a.get("advisor_name") or sid
            for sid, a in lookups.advisor_rows(columns="advisor_name").items()}


def exception_rules(version_id: str | None = None) -> list[dict]:
    """The PUBLISHED + active + exception_enabled rules of the served version."""
    from app.rules.seed import ensure_v0_seed
    from app.rules.store import get_rule_store

    ensure_v0_seed()
    store = get_rule_store()
    version = (store.version(version_id) if version_id
               else store.latest_version("PUBLISHED"))
    if version is None:
        return []
    return [r for r in store.version_rules(version["version_id"])
            if r.get("status") in ("PUBLISHED", "SUPERSEDED")
            and r.get("active") is not False
            and r.get("exception_enabled") is True]


def _matched_by_advisor(rule: dict, month: str, sids: list[str],
                        version_id: str) -> dict[str, list[dict]]:
    """advisor_sid -> matched entries ({key, value, ...}) for this rule in
    this month, evaluated per advisor at advisor scope (exclusion chains and
    scope semantics identical to insight generation)."""
    from app.rules.service import evaluate_rule_set

    out: dict[str, list[dict]] = {}
    for sid in sids:
        try:
            outcome = evaluate_rule_set(version_id, month=month,
                                        advisor_sid=sid, scope="advisor")
        except Exception as exc:  # noqa: BLE001 — one advisor never sinks the model
            _log.warning("exception evaluation failed for %s: %s", sid, exc)
            continue
        for result in outcome["results"]:
            if result.get("rule_key") != rule.get("rule_key"):
                continue
            if result.get("evaluated") and result.get("matched"):
                out[sid] = result["matched"]
    return out


def _trigger_fires(op: str, value: float, threshold: float) -> bool:
    return {"=": value == threshold, "!=": value != threshold,
            ">": value > threshold, ">=": value >= threshold,
            "<": value < threshold, "<=": value <= threshold}[op]


def _absolute_firm_exception(rule: dict, month: str, version_id: str) -> dict:
    """Round 8 task 4 — a PRACTICE-applies rule is an ABSOLUTE firm-level
    threshold, not a cohort rate: there is no peer cohort at firm level, so the
    rate model does not apply.

    Round 9 task 10c — ONE authoritative source: the passed-in rule's own
    plan. The plan runs once with its trigger opened to observe the actual
    value, and ``fired`` is that observation compared against the same plan's
    own trigger — never a second evaluation reading the store again, which
    could disagree with the rule this function was handed."""
    from app.graph.queries.catalog import run_catalog_query
    from app.rules.compiler import translate_plan

    plan = rule.get("plan") or {}
    trigger = plan.get("trigger") or {}
    threshold = trigger.get("value")
    op = str(trigger.get("op") or ">")
    fired = False
    observed = None
    error = None
    try:
        open_plan = dict(plan)
        open_plan["trigger"] = {"op": ">=", "value": -1e18}
        compiled = translate_plan(rule.get("rule_code") or "", "month", open_plan)
        rows = run_catalog_query(
            "rules_evaluate_plan",
            {"plan": compiled.plan, "params": {"month": month}},
            allow_internal=True)
        entries = (rows.get("rows") or [{}])[0].get("matched") or []
        fired_entries = [e for e in entries
                         if _trigger_fires(op, _f(e.get("value")), _f(threshold))]
        fired = bool(fired_entries)
        source = fired_entries if fired else entries
        observed = round(sum(_f(e.get("value")) for e in source), 2) \
            if source else 0.0
    except Exception as exc:  # noqa: BLE001 — stated, never hidden
        error = f"{type(exc).__name__}: {exc}"
    monetary = _rule_is_monetary(rule)
    return {
        "rule_key": rule.get("rule_key"), "rule_code": rule.get("rule_code"),
        "rule_name": rule.get("rule_name") or rule.get("rule_code"),
        "severity": rule.get("severity"),
        "model": "absolute_threshold",
        "config": {
            "exception_denominator": None,
            "denominator_label": "absolute firm-level threshold — no cohort",
            "denominator_kind": "absolute",
            "product_scope": rule.get("product_scope") or None,
            "product_scope_applied": "firm level — no narrowing",
            "exception_floor": None, "exception_floor_unit": None,
            "exception_sensitivity": None, "sensitivity_applied": None,
            "sensitivity_default_used": False,
            "threshold": threshold,
            "threshold_op": trigger.get("op"),
        },
        "cohort": {"median_pct": None, "stdev_pct": None,
                   "flag_threshold_pct": None, "in_scope_advisors": 0},
        "advisors": [],
        "firm": {
            "affected": 1 if fired else 0,
            "denominator": 1, "rate_pct": None,
            "advisors_in_scope": 0, "advisors_flagged": 0,
            "advisors_with_exceptions": 0,
            "impact_amt": observed if (fired and monetary) else None,
            "observed_value": observed,
            "threshold": threshold, "fired": fired,
            "is_monetary": monetary,
            "error": error,
        },
        "month": month,
    }


def _practice_unsupported(rule: dict, month: str) -> dict:
    """Round 9 task 6 — a PRACTICE-applies rule WITHOUT a numeric trigger fits
    neither exceptions model: the absolute-threshold branch has no threshold
    to compare, and the rate model has no per-advisor evaluation (applies_to
    PRACTICE confines the rule to firm-level runs). Say exactly that instead
    of producing a zero-filled firm row."""
    note = ("this PRACTICE-applies rule has no numeric trigger, so the "
            "absolute firm-level threshold model cannot evaluate it — and "
            "applies_to=PRACTICE excludes per-advisor evaluation, so the "
            "cohort rate model cannot either. Give the rule's plan a numeric "
            "trigger, or re-tag applies_to (e.g. ALL/ADVISOR) so it can be "
            "measured per advisor.")
    return {
        "rule_key": rule.get("rule_key"), "rule_code": rule.get("rule_code"),
        "rule_name": rule.get("rule_name") or rule.get("rule_code"),
        "severity": rule.get("severity"),
        "model": "unsupported",
        "config": {
            "exception_denominator": None,
            "denominator_label": "not evaluable — see note",
            "denominator_kind": "unsupported",
            "product_scope": rule.get("product_scope") or None,
            "product_scope_applied": None,
            "exception_floor": None, "exception_floor_unit": None,
            "exception_sensitivity": None, "sensitivity_applied": None,
            "sensitivity_default_used": False,
            "threshold": None, "threshold_op": None,
        },
        "cohort": {"median_pct": None, "stdev_pct": None,
                   "flag_threshold_pct": None, "in_scope_advisors": 0},
        "advisors": [],
        "firm": {"affected": None, "denominator": None, "rate_pct": None,
                 "advisors_in_scope": 0, "advisors_flagged": 0,
                 "advisors_with_exceptions": 0, "impact_amt": None,
                 "observed_value": None, "threshold": None, "fired": None,
                 "is_monetary": _rule_is_monetary(rule),
                 "error": None, "note": note},
        "month": month,
    }


def compute_rule_exceptions(rule: dict, month: str, *,
                            sids: list[str] | None = None,
                            accounts_by_advisor: dict[str, list[dict]] | None = None,
                            prior_accounts: dict[str, list[dict]] | None = None,
                            version_id: str | None = None) -> dict:
    """The full rate model for ONE rule: per-advisor rows, cohort statistics
    and the firm rollup. A PRACTICE-applies rule takes the absolute-threshold
    branch instead — there is no peer cohort at firm level (Round 8 task 4)."""
    from app.rules.store import get_rule_store

    version_id = version_id or get_rule_store().latest_version("PUBLISHED")["version_id"]
    if rule.get("applies_to") == "PRACTICE":
        # Round 9 task 6 — the absolute-threshold branch requires a NUMERIC
        # trigger, matching the UI editor's own condition (ExceptionsTab keys
        # on applies_to PRACTICE + a numeric trigger). A PRACTICE rule without
        # one (e.g. an account-grain rule re-tagged PRACTICE) must never be
        # silently collapsed into a firm-level scalar of zeros.
        trigger_value = ((rule.get("plan") or {}).get("trigger") or {}).get("value")
        if isinstance(trigger_value, (int, float)) \
                and not isinstance(trigger_value, bool):
            return _absolute_firm_exception(rule, month, version_id)
        return _practice_unsupported(rule, month)
    sids = sids or _cohort_sids()
    accounts_by_advisor = accounts_by_advisor or _advisor_accounts(month)
    kind, denominator_label = _denominator_kind(rule)
    managed_only = kind == "managed_accounts" or _scope_is_managed(rule.get("product_scope"))
    if kind == "revenue":
        prior = _prior_month(month)
        prior_accounts = prior_accounts or (_advisor_accounts(prior) if prior else {})

    matched = _matched_by_advisor(rule, month, sids, version_id)
    floor = rule.get("exception_floor")
    floor_unit = (rule.get("exception_floor_unit") or "accounts").lower()
    sensitivity = rule.get("exception_sensitivity")
    sens = _f(sensitivity) if sensitivity not in (None, "") else DEFAULT_SENSITIVITY

    rows: list[dict] = []
    for sid in sids:
        accts = accounts_by_advisor.get(sid, [])
        scoped = [a for a in accts if a["is_managed"]] if managed_only else accts
        scoped_keys = {str(a.get("acct_key")) for a in scoped}
        entries = matched.get(sid, [])
        if kind == "revenue":
            prior_rows = (prior_accounts or {}).get(sid, [])
            denominator = round(sum(_f(a.get("credited_amt")) for a in prior_rows), 2)
            affected = round(sum(_f(e.get("value")) for e in entries), 2)
            affected_count = len(entries)
        else:
            denominator = len(scoped_keys) if managed_only else len(accts)
            in_scope_entries = ([e for e in entries if str(e.get("key")) in scoped_keys]
                                if managed_only else entries)
            affected = len(in_scope_entries)
            affected_count = len(in_scope_entries)
        if denominator <= 0:
            continue  # out of scope — never drags the cohort median down
        rate_pct = round(affected / denominator * 100, 2)
        affected_amt = round(sum(_f(e.get("value")) for e in entries), 2)
        rows.append({
            "advisor_sid": sid, "affected": affected,
            "affected_count": affected_count, "affected_amt": affected_amt,
            "denominator": denominator, "rate_pct": rate_pct,
        })

    rates = [r["rate_pct"] for r in rows]
    cohort_median = round(median(rates), 2) if rates else None
    cohort_stdev = round(stdev(rates), 2) if len(rates) >= 2 else 0.0
    threshold = (round(cohort_median + sens * cohort_stdev, 2)
                 if cohort_median is not None else None)

    names = _advisor_names()
    for r in rows:
        r["advisor_name"] = names.get(r["advisor_sid"], r["advisor_sid"])
        r["cohort_median_pct"] = cohort_median
        suppressed = None
        if floor not in (None, ""):
            if floor_unit == "dollars":
                if abs(r["affected_amt"]) < _f(floor):
                    suppressed = (f"below the materiality floor — "
                                  f"${abs(r['affected_amt']):,.0f} affected < "
                                  f"${_f(floor):,.0f} floor")
            elif r["affected_count"] < _f(floor):
                suppressed = (f"below the materiality floor — "
                              f"{r['affected_count']} affected accounts < "
                              f"{int(_f(floor))} floor")
        r["suppressed_reason"] = suppressed
        r["flagged"] = (suppressed is None and threshold is not None
                        and r["rate_pct"] > threshold and r["affected_count"] > 0)
    rows.sort(key=lambda r: -r["rate_pct"])

    monetary = _rule_is_monetary(rule)
    firm_affected = round(sum(r["affected"] for r in rows), 2)
    firm_denominator = round(sum(r["denominator"] for r in rows), 2)
    firm = {
        "affected": firm_affected,
        "denominator": firm_denominator,
        "rate_pct": (round(firm_affected / firm_denominator * 100, 2)
                     if firm_denominator else None),
        "advisors_in_scope": len(rows),
        "advisors_flagged": sum(1 for r in rows if r["flagged"]),
        "advisors_with_exceptions": sum(1 for r in rows if r["affected_count"] > 0),
        "impact_amt": (round(sum(r["affected_amt"] for r in rows), 2)
                       if monetary else None),
    }
    return {
        "rule_key": rule.get("rule_key"), "rule_code": rule.get("rule_code"),
        "rule_name": rule.get("rule_name") or rule.get("rule_code"),
        "severity": rule.get("severity"),
        "config": {
            "exception_denominator": rule.get("exception_denominator"),
            "denominator_label": denominator_label,
            "denominator_kind": kind,
            "product_scope": rule.get("product_scope") or None,
            "product_scope_applied": ("managed accounts only" if managed_only
                                      else "no narrowing"),
            "exception_floor": rule.get("exception_floor"),
            "exception_floor_unit": rule.get("exception_floor_unit"),
            "exception_sensitivity": (sens if sensitivity not in (None, "")
                                      else None),
            "sensitivity_applied": sens,
            "sensitivity_default_used": sensitivity in (None, ""),
        },
        "cohort": {"median_pct": cohort_median, "stdev_pct": cohort_stdev,
                   "flag_threshold_pct": threshold,
                   "in_scope_advisors": len(rows)},
        "advisors": rows,
        "firm": firm,
        "month": month,
    }


def _rule_is_monetary(rule: dict) -> bool:
    plan = rule.get("plan") or {}
    compute = plan.get("compute") or {}
    return compute.get("agg") == "sum" and "_amt" in str(compute.get("expr") or "")


def compute_firm_exceptions(month: str, version_id: str | None = None) -> dict:
    """One row per exception-enabled rule — the firm altitude. The row count
    is the number of RULES, so it stays readable at any scale.

    Round 8 tasks 2/3: the response also states the SERVED VERSION and its
    published-rule count, so the UI can distinguish three different empties —
    no published rules at all, rules published but none exception-enabled,
    and exceptions enabled that simply matched nothing this period (the third
    is a result, not a problem)."""
    from app.rules.store import get_rule_store

    store = get_rule_store()
    version = (store.version(version_id) if version_id
               else store.latest_version("PUBLISHED"))
    published_rules = ([r for r in store.version_rules(version["version_id"])
                        if r.get("status") in ("PUBLISHED", "SUPERSEDED")
                        and r.get("active") is not False]
                       if version is not None else [])
    rules = exception_rules(version_id)
    sids = _cohort_sids()
    accounts = _advisor_accounts(month)
    prior = _prior_month(month)
    prior_accounts = _advisor_accounts(prior) if prior else {}
    rows = []
    for rule in rules:
        full = compute_rule_exceptions(rule, month, sids=sids,
                                       accounts_by_advisor=accounts,
                                       prior_accounts=prior_accounts,
                                       version_id=version_id)
        rows.append({k: full[k] for k in ("rule_key", "rule_code", "rule_name",
                                          "severity", "config", "cohort", "firm")
                     if k in full} | {"model": full.get("model") or "rate"})
    return {"month": month, "rules": rows, "rule_count": len(rows),
            "published_version": version["version_id"] if version else None,
            "published_rule_count": len(published_rules)}


def compute_advisor_exceptions(advisor_sid: str, month: str,
                               version_id: str | None = None) -> dict:
    """The advisor altitude: their rate against the cohort median, per rule —
    '8 of 30, 26.7%, median 4.1%'. An advisor seeing '8 accounts' learns
    nothing."""
    rules = exception_rules(version_id)
    sids = _cohort_sids()
    accounts = _advisor_accounts(month)
    prior = _prior_month(month)
    prior_accounts = _advisor_accounts(prior) if prior else {}
    out = []
    for rule in rules:
        full = compute_rule_exceptions(rule, month, sids=sids,
                                       accounts_by_advisor=accounts,
                                       prior_accounts=prior_accounts,
                                       version_id=version_id)
        mine = next((r for r in full["advisors"]
                     if r["advisor_sid"] == advisor_sid), None)
        if full.get("model") == "absolute_threshold":
            mine = {"advisor_sid": advisor_sid, "in_scope": False,
                    "note": "firm-level absolute threshold — not evaluated "
                            "per advisor"}
        elif full.get("model") == "unsupported":
            mine = {"advisor_sid": advisor_sid, "in_scope": False,
                    "note": full["firm"]["note"]}
        out.append({
            "rule_key": full["rule_key"], "rule_code": full["rule_code"],
            "rule_name": full["rule_name"], "severity": full["severity"],
            "config": full["config"], "cohort": full["cohort"],
            "model": full.get("model") or "rate",
            "position": mine or {"advisor_sid": advisor_sid,
                                 "in_scope": False,
                                 "note": "no in-scope denominator this month"},
        })
    return {"advisor_sid": advisor_sid, "month": month, "rules": out}

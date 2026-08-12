"""Round G task 3 — the drill-down backend (ROUND_G_SPEC 3 / ROUND_G_INTERFACE §3).

Four levels, three of which produce a STORED insight run scoped to what was
clicked (product / product_advisor / product_account); the transaction level is
a deterministic listing — NO LLM, no run, ever.

Scope model (contract §1):

    run_id = scope|scope_key|from_month|to_month|version_id
    scope_key parts joined with "~":
        product          managed_accounts
        product_advisor  managed_accounts~V000002
        product_account  managed_accounts~V000002~3060

Scoped runs reuse the SAME Miner (``mine``) and Reporter (``report``) with a
narrower opening context and smaller budgets (settings-resolved, Round H:
DRILLDOWN_PRODUCT_QUERY_BUDGET/TURN_CAP and DRILLDOWN_SUB_QUERY_BUDGET/
TURN_CAP; defaults product 8 queries / 12 turns, sub-scopes 6 / 10). ``mine``
has no turns parameter, so the turn cap is enforced by ``_TurnCappedLLM`` — a
wrapper that counts LLM calls and answers ``{"action":"done"}`` itself once the
cap is reached. Rule evaluation runs at the mapped rule scope
(product→"product", product_advisor→"product_advisor", product_account→
"account"); rules not applicable at that scope are skipped (Round G task 1).

Store integration (contract §2): ``scoped_run_id`` / ``begin_scoped_run`` /
``generation_lock`` are implemented in app/insights/store.py (Round G task 5).
"""
from __future__ import annotations

from app.graph.queries.catalog import MOVEMENT_CAUSES_NOTE, run_catalog_query
from app.insights.store import get_insight_store
from app.insights.store import scoped_run_id as _store_scoped_run_id
from app.insights.tools import MinerTools
from app.shared.logging import get_logger

_log = get_logger("app.insights.drilldown")

DRILLDOWN_SCOPES = ("product", "product_advisor", "product_account")

# drill-down scope -> rule-evaluation scope (contract §1)
RULE_SCOPE = {"product": "product", "product_advisor": "product_advisor",
              "product_account": "account"}

# drill-down scope -> (query budget, LLM turn cap) — ROUND_G_SPEC 3.3.
# Round H task 2: resolved from settings (DRILLDOWN_PRODUCT_QUERY_BUDGET /
# DRILLDOWN_PRODUCT_TURN_CAP / DRILLDOWN_SUB_QUERY_BUDGET /
# DRILLDOWN_SUB_TURN_CAP), no module constants.
def budgets_for(scope: str) -> tuple[int, int]:
    from app.config.settings import get_settings

    s = get_settings()
    if scope == "product":
        return s.drilldown_product_query_budget, s.drilldown_product_turn_cap
    return s.drilldown_sub_query_budget, s.drilldown_sub_turn_cap

# scope -> its parent scope in the drill-down chain (None at the top)
PARENT_SCOPE = {"product": None, "product_advisor": "product",
                "product_account": "product_advisor"}

# Honest static fallback for the pre-generation estimate when no scoped run has
# ever completed — clearly labelled as such in the payload's ``basis``.
STATIC_ESTIMATE = {"cost_usd": 0.02, "seconds": 20}


class DrilldownError(ValueError):
    """Bad scope / scope_key / months — raised before any work happens."""


# --------------------------------------------------------------------------- scope model


def split_scope_key(scope: str, scope_key: str) -> dict:
    """scope_key parts -> {"group_id", "advisor_sid"?, "acct_key"?}."""
    if scope not in DRILLDOWN_SCOPES:
        raise DrilldownError(
            f"unknown drill-down scope {scope!r} — expected one of "
            f"{', '.join(DRILLDOWN_SCOPES)}")
    parts = str(scope_key).split("~")
    expected = {"product": 1, "product_advisor": 2, "product_account": 3}[scope]
    if len(parts) != expected or not all(parts):
        raise DrilldownError(
            f"scope_key {scope_key!r} does not match scope {scope!r} "
            f"(expected {expected} '~'-joined part(s))")
    out = {"group_id": parts[0]}
    if len(parts) > 1:
        out["advisor_sid"] = parts[1]
    if len(parts) > 2:
        out["acct_key"] = parts[2]
    return out


def make_scope_key(group_id: str, advisor_sid: str | None = None,
                   acct_key: str | None = None) -> str:
    parts = [str(group_id)]
    if advisor_sid:
        parts.append(str(advisor_sid))
    if acct_key:
        parts.append(str(acct_key))
    return "~".join(parts)


def scoped_run_id(scope: str, scope_key: str, from_month: str, to_month: str,
                  version_id: str) -> str:
    return _store_scoped_run_id(scope, scope_key, from_month, to_month, version_id)


def _generation_lock(store, run_id: str):
    return store.generation_lock(run_id)


def _begin_scoped_run(store, scope: str, scope_key: str, from_month: str,
                      to_month: str, version_id: str,
                      parent_run_id: str | None) -> dict:
    return store.begin_scoped_run(scope, scope_key, from_month, to_month,
                                  version_id, parent_run_id=parent_run_id)


# --------------------------------------------------------------------------- turn cap


class _TurnCappedLLM:
    """Caps the Miner's LLM turns WITHOUT editing app/agents/: after
    ``max_turns`` real calls it stops forwarding and answers
    {"action":"done"} itself (mine()'s zero-finding nudge may draw one or two
    further forced dones — those never reach the real LLM either)."""

    _FORCED = '{"action":"done","note":"scoped turn cap reached"}'

    def __init__(self, inner, max_turns: int) -> None:
        self._inner = inner
        self._max = max_turns
        self.calls = 0
        # Round H 2.3: a bound cap is recorded, never silent.
        self.limits_hit: list[dict] = []

    def _capped(self) -> bool:
        self.calls += 1
        if self.calls > self._max:
            if not self.limits_hit:
                self.limits_hit.append({
                    "limit_name": "DRILLDOWN_TURN_CAP",
                    "limit_value": self._max,
                    "limit_effect": (
                        f"the scoped run reached its {self._max}-turn cap; the "
                        f"run was closed with the findings formed so far")})
            return True
        return False

    def __call__(self, prompt: str, ctx: dict) -> str:
        if self._capped():
            return self._FORCED
        return self._inner(prompt, ctx)

    def converse(self, system_blocks, messages) -> str:
        if self._capped():
            return self._FORCED
        return self._inner.converse(system_blocks, messages)

    @property
    def supports_conversation(self) -> bool:
        return bool(getattr(self._inner, "supports_conversation", False))

    def __getattr__(self, name: str):
        # tag_last / prompt_tokens_total etc. pass through to the wrapper
        return getattr(self._inner, name)


# --------------------------------------------------------------------------- deterministic parts


def level_parts(scope: str, scope_key: str, from_month: str, to_month: str) -> dict:
    """The deterministic (query-only, no-LLM) parts of one level: metric strip,
    movement causes (product level only) and the contribution rows whose rows
    open the next level."""
    parts = split_scope_key(scope, scope_key)
    gid = parts["group_id"]
    if scope == "product":
        metrics = run_catalog_query("product_transition_metrics", {
            "group_id": gid, "from_month": from_month, "to_month": to_month,
        })["rows"][0]
        causes = run_catalog_query("product_movement_causes", {
            "group_id": gid, "from_month": from_month, "to_month": to_month,
        })["rows"][0]
        causes.setdefault("note", MOVEMENT_CAUSES_NOTE)
        contributions = run_catalog_query("product_advisors", {
            "group_id": gid, "from_month": from_month, "to_month": to_month,
        })["rows"]
        return {"metrics": metrics, "movement_causes": causes,
                "contributions": contributions}
    if scope == "product_advisor":
        sid = parts["advisor_sid"]
        advisors = run_catalog_query("product_advisors", {
            "group_id": gid, "from_month": from_month, "to_month": to_month,
        })["rows"]
        mine_row = next((r for r in advisors if r["advisor_sid"] == sid), None)
        if mine_row is None:
            mine_row = {"advisor_sid": sid, "from_amt": 0.0, "to_amt": 0.0,
                        "change_amt": 0.0, "account_count": 0,
                        "is_new_to_product": False}
        contributions = run_catalog_query("product_advisor_accounts", {
            "group_id": gid, "advisor": sid,
            "from_month": from_month, "to_month": to_month,
        })["rows"]
        return {"metrics": mine_row, "movement_causes": None,
                "contributions": contributions}
    # product_account
    sid, acct = parts["advisor_sid"], parts["acct_key"]
    accounts = run_catalog_query("product_advisor_accounts", {
        "group_id": gid, "advisor": sid,
        "from_month": from_month, "to_month": to_month,
    })["rows"]
    mine_row = next((r for r in accounts if r["acct_key"] == acct), None)
    if mine_row is None:
        raise DrilldownError(
            f"account '{acct}' has no {gid} activity for advisor '{sid}' "
            f"in {from_month}->{to_month}")
    contributions = run_catalog_query("product_account_txns", {
        "group_id": gid, "advisor": sid, "acct_key": acct, "month_id": to_month,
    })["rows"]
    return {"metrics": mine_row, "movement_causes": None,
            "contributions": contributions}


def txn_level(group_id: str, advisor_sid: str, acct_key: str,
              from_month: str, to_month: str) -> dict:
    """The transaction level — deterministic listing, NO LLM ever (there is no
    security identifier in the data, so 'why' runs out here). Contract §4."""
    base = {"group_id": group_id, "advisor": advisor_sid, "acct_key": acct_key}
    from_txns = run_catalog_query("product_account_txns",
                                  {**base, "month_id": from_month})["rows"]
    to_txns = run_catalog_query("product_account_txns",
                                {**base, "month_id": to_month})["rows"]
    balance_rows = run_catalog_query("product_advisor_accounts", {
        "group_id": group_id, "advisor": advisor_sid,
        "from_month": from_month, "to_month": to_month})["rows"]
    acct_row = next((r for r in balance_rows if r["acct_key"] == acct_key), {})
    return {
        "generated": True, "llm": False,
        "metrics": {
            "from_txn_count": len(from_txns), "to_txn_count": len(to_txns),
            "to_amt": round(sum(float(t["credited_amt"] or 0) for t in to_txns), 2),
            "end_balance": acct_row.get("end_balance", 0.0),
        },
        "transactions": to_txns,
    }


# --------------------------------------------------------------------------- estimates


def _estimate(store) -> dict:
    """Cost/time estimate for a not-yet-generated level, from the Trace summary
    figures (est_cost_usd / wall_ms) of prior COMPLETE scoped runs; when none
    exist, an explicitly labelled static estimate — never a fabricated one."""
    scoped = [r for r in store.runs.values()
              if r.get("status") == "COMPLETE"
              and r["run_id"].split("|", 1)[0] in DRILLDOWN_SCOPES]
    if scoped:
        return {"cost_usd": round(sum(float(r.get("est_cost_usd") or 0)
                                      for r in scoped) / len(scoped), 4),
                "seconds": max(1, round(sum(int(r.get("wall_ms") or 0)
                                            for r in scoped) / len(scoped) / 1000)),
                "basis": f"average of {len(scoped)} prior scoped run(s)"}
    return {**STATIC_ESTIMATE,
            "basis": "static estimate — no scoped run has completed yet"}


# --------------------------------------------------------------------------- get / generate


def _published_version(version_id: str | None = None) -> dict:
    from app.insights.service import _published_version as latest
    from app.rules.store import get_rule_store

    if version_id:
        version = get_rule_store().version(version_id)
        if version is None:
            raise DrilldownError(f"unknown rule-set version {version_id!r}")
        return version
    return latest()


def get_drilldown(scope: str, scope_key: str, from_month: str, to_month: str,
                  version_id: str | None = None) -> dict:
    """Contract §4 level payload. Deterministic parts ALWAYS; the AI parts only
    when a COMPLETE stored run exists, else an estimate. Never generates."""
    version = _published_version(version_id)
    store = get_insight_store()
    run_id = scoped_run_id(scope, scope_key, from_month, to_month,
                           version["version_id"])
    parts = level_parts(scope, scope_key, from_month, to_month)
    run = store.run(run_id)  # C's rehydration path raises loudly if broken
    payload = {
        "generated": bool(run and run.get("status") == "COMPLETE"),
        "scope": scope, "scope_key": scope_key,
        "from_month": from_month, "to_month": to_month,
        "run_id": None, "parent_run_id": None,
        "metrics": parts["metrics"],
        "movement_causes": parts["movement_causes"],
        "contributions": parts["contributions"],
    }
    if payload["generated"]:
        import json as _json

        payload["run_id"] = run_id
        payload["parent_run_id"] = run.get("parent_run_id")
        payload["narrative"] = run.get("narrative") or ""
        payload["bullets"] = _json.loads(run.get("bullets_json") or "[]")
        payload["findings"] = store.run_findings(run_id)
        # Round H 2.3/4.1: limits that bound on the scoped run, loud.
        limits = _json.loads(run.get("limits_json") or "[]")
        payload["limit_hit"] = bool(limits)
        payload["limits_hit"] = limits
        payload["stored"] = {
            "generated_at": run.get("completed_at") or run.get("started_at"),
            "version_id": version["version_id"],
            "version_no": version.get("version_no"),
        }
    else:
        payload["estimate"] = _estimate(store)
    return payload


def _parent_run_id(store, scope: str, parts: dict, from_month: str,
                   to_month: str, version_id: str) -> str | None:
    """The run one level up when it exists, else None (contract §1)."""
    parent_scope = PARENT_SCOPE[scope]
    if parent_scope is None:
        return None
    if parent_scope == "product":
        key = make_scope_key(parts["group_id"])
    else:  # product_advisor
        key = make_scope_key(parts["group_id"], parts["advisor_sid"])
    rid = scoped_run_id(parent_scope, key, from_month, to_month, version_id)
    parent = store.run(rid)
    return rid if parent and parent.get("status") == "COMPLETE" else None


def _scoped_rule_findings(scope: str, parts: dict, to_month: str,
                          version: dict) -> tuple[list[dict], list[dict]]:
    """Evaluate the published rules at the mapped rule scope — rules not
    applicable there are skipped, never errored (Round G task 1)."""
    from app.insights.service import _monetary_impact
    from app.rules.service import evaluate_rule_set
    from app.rules.store import get_rule_store

    rule_scope = RULE_SCOPE[scope]
    advisor_sid = parts.get("advisor_sid")
    outcome = evaluate_rule_set(version["version_id"], month=to_month,
                                advisor_sid=advisor_sid, scope=rule_scope)
    rule_map = {r["rule_key"]: r
                for r in get_rule_store().version_rules(version["version_id"])}
    findings: list[dict] = []
    outcomes: list[dict] = []
    for result in outcome["results"]:
        rule = rule_map.get(result.get("rule_key")) or {}
        outcomes.append({
            "rule_code": result.get("rule_code"),
            "rule_key": result.get("rule_key"),
            "evaluated": result.get("evaluated", False),
            "matched_count": result.get("matched_count", 0),
            "error": result.get("error"),
            "empty_reason": result.get("empty_reason"),
            "skipped": result.get("skipped", False),
            "skip_reason": result.get("skip_reason"),
        })
        matched = result.get("matched") or []
        if not (result.get("evaluated") and matched):
            continue
        citations = rule.get("citations") or []
        # Round H: no cap here — the store applies EVIDENCE_STORED_CAP and
        # records the bind (same fix as app/insights/service.py; a hardcoded
        # [:50] silently under-reported evidence_total past 50 matches).
        evidence_rows = list(matched)
        findings.append({
            "title": f"{rule.get('rule_name') or result.get('rule_code')} — "
                     f"{len(matched)} match(es) in {to_month}",
            "summary": (f"Rule {result.get('rule_code')} fired for {len(matched)} "
                        f"{rule.get('grain') or 'entity'}(s) in {to_month} at "
                        f"{rule_scope} scope. {rule.get('statement') or ''}").strip(),
            "impact_amt": _monetary_impact(rule, matched),
            "driver_tag": rule.get("driver_tag") or "Other",
            "group_id": parts["group_id"],
            "rule_key": result.get("rule_key"),
            "provenance": "REAL",
            "confidence": 1.0,
            "evidence_columns": sorted(evidence_rows[0].keys()) if evidence_rows else [],
            "evidence_rows": evidence_rows,
            "evidence_reason": None,
            "citation": citations[0] if citations else None,
            "origin": "rule",
            "source_query": {"query_name": "rules_evaluate_plan",
                             "params": {"rule_code": result.get("rule_code"),
                                        "month": to_month,
                                        "advisor_sid": advisor_sid,
                                        "scope": rule_scope}},
        })
    return findings, outcomes


def _run_scoped_insight(scope: str, scope_key: str, from_month: str,
                        to_month: str, version: dict,
                        miner_llm=None, reporter_llm=None) -> dict:
    """One scoped mine → report → persist cycle (mirrors
    service.run_insights_for_advisor with narrower context and budgets)."""
    from app.agents.insights_miner import mine
    from app.agents.insights_reporter import report
    from app.insights.service import _resolve_llm_client
    from app.rules.store import get_rule_store

    parts = split_scope_key(scope, scope_key)
    store = get_insight_store()
    rules = [r for r in get_rule_store().version_rules(version["version_id"])
             if r.get("status") in ("PUBLISHED", "SUPERSEDED")]
    query_budget, turn_cap = budgets_for(scope)

    # The scoped metrics ARE the transition the Miner explains; the scope is
    # stated inside the TOTALS line of the opening (mine() serialises the whole
    # transition dict there — app/agents/ stays untouched).
    metrics = level_parts(scope, scope_key, from_month, to_month)["metrics"]
    transition = {
        "scope": scope, "scope_key": scope_key,
        "scope_statement": f"This run is SCOPED to {scope} {scope_key} — "
                           f"explain ONLY this slice's change, not the whole book.",
        **{k: v for k, v in metrics.items()},
    }

    rule_findings, rule_outcomes = _scoped_rule_findings(scope, parts, to_month,
                                                         version)
    rule_impacts = sum(f["impact_amt"] for f in rule_findings
                       if f["impact_amt"] is not None)
    residual_amt = round(float(transition.get("change_amt") or 0.0) - rule_impacts, 2)

    parent_run_id = _parent_run_id(store, scope, parts, from_month, to_month,
                                   version["version_id"])
    run = _begin_scoped_run(store, scope, scope_key, from_month, to_month,
                            version["version_id"], parent_run_id)
    tools = MinerTools(run["run_id"], budget=query_budget,
                       budget_limit_name=(
                           "DRILLDOWN_PRODUCT_QUERY_BUDGET" if scope == "product"
                           else "DRILLDOWN_SUB_QUERY_BUDGET"))
    try:
        from app.llm.usage import wrap_llm

        miner = miner_llm or wrap_llm(_resolve_llm_client("insights_miner"),
                                      run["run_id"], "insights_miner")
        reporter = reporter_llm or wrap_llm(_resolve_llm_client("insights_reporter"),
                                            run["run_id"], "insights_reporter")
        capped_miner = _TurnCappedLLM(miner, turn_cap)
        # advisor_sid drives the Miner's initial revenue_change_by_product call
        # and the opening's ADVISOR line: the scoped advisor when the scope_key
        # carries one, else the whole cohort.
        mined = mine(advisor_sid=parts.get("advisor_sid") or "all",
                     from_month=from_month, to_month=to_month,
                     rules=rules, transition=transition, tools=tools,
                     llm=capped_miner, rule_findings=rule_findings,
                     rule_outcomes=rule_outcomes, residual_amt=residual_amt)
        from app.insights.reporter_sources import build_reporter_search

        reported = report(mined["findings"], transition, reporter,
                          search_documents=build_reporter_search(run["run_id"]))
        completed = store.complete_run(
            run["run_id"], narrative=reported["narrative"],
            bullets=reported["bullets"],
            recommendations=reported.get("recommendations") or [],
            findings=mined["findings"], query_count=mined["query_count"],
            budget_hit=mined["budget_hit"],
            budget_hit_tokens=mined.get("budget_hit_tokens", False),
            limits_hit=(mined.get("limits_hit") or []) + capped_miner.limits_hit,
            coverage_ratio=mined["coverage_ratio"])
        return completed
    except Exception as exc:  # noqa: BLE001 — honest failure recorded on the run
        _log.exception("scoped insight run %s failed", run["run_id"])
        store.fail_run(run["run_id"], f"{type(exc).__name__}: {exc}")
        raise


def generate_drilldown(scope: str, scope_key: str, from_month: str,
                       to_month: str, version_id: str | None = None,
                       miner_llm=None, reporter_llm=None) -> dict:
    """Contract §3 generation flow: run_id → stored hit → return; miss → take
    the generation lock, re-check, generate, complete. A concurrent duplicate
    request blocks on the lock and returns the first requester's stored
    result. Returns the same payload as get_drilldown (generated: true)."""
    if scope not in DRILLDOWN_SCOPES:
        raise DrilldownError(
            f"unknown drill-down scope {scope!r} — the transaction level is "
            f"deterministic and never generated")
    version = _published_version(version_id)
    store = get_insight_store()
    run_id = scoped_run_id(scope, scope_key, from_month, to_month,
                           version["version_id"])
    existing = store.run(run_id)
    if existing and existing.get("status") == "COMPLETE":
        return get_drilldown(scope, scope_key, from_month, to_month,
                             version["version_id"])
    with _generation_lock(store, run_id) as should_generate:
        rechecked = store.run(run_id)
        if should_generate and not (rechecked
                                    and rechecked.get("status") == "COMPLETE"):
            _run_scoped_insight(scope, scope_key, from_month, to_month, version,
                                miner_llm=miner_llm, reporter_llm=reporter_llm)
    return get_drilldown(scope, scope_key, from_month, to_month,
                         version["version_id"])

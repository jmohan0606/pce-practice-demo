"""Round A2B task 6 — the iPerform Advisor AI Insights page's API.

GET  /api/advisor/list                       sid, name, rep_code, in_cohort
GET  /api/advisor/{sid}/summary?from=&to=    team chip, per-month AUM, metrics
                                             strip (lifecycle, AUM, NCF, trades;
                                             real NNM lives at /{sid}/nnm)
GET  /api/advisor/{sid}/peer-ranking?from=&to=  revenue / growth / discount-rate
POST /api/advisor/{sid}/coaching/generate    runs the Coach (stored durably)
GET  /api/advisor/{sid}/coaching             the stored result — no regeneration
GET  /api/advisor/{sid}/opportunities        CRM pipeline (real extract shape)

Every figure is a catalog-query result or a straight vertex read; the router
composes, it computes no business numbers of its own. Missing data serializes
as null with a note — never a guess.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.flags.registry import require_feature
from app.graph.queries.catalog import CatalogError, run_catalog_query
from app.shared.logging import get_logger

_log = get_logger("app.api.advisor")

router = APIRouter(prefix="/api/advisor", tags=["advisor"])

def _catalog(name: str, params: dict) -> list[dict]:
    try:
        return run_catalog_query(name, params)["rows"]
    except CatalogError as exc:
        raise HTTPException(400, str(exc)) from exc


def _store():
    from app.graph.foundation_store import get_foundation_store

    return get_foundation_store()


def _advisor_row(sid: str) -> dict:
    row = _store().all_vertices("phx_dm_pce_advisor").get(sid)
    if row is None:
        raise HTTPException(404, f"unknown advisor '{sid}'")
    return row


def _month_ids() -> list[str]:
    return sorted(_store().all_vertices("phx_dm_pce_month"))


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


@router.get("/list")
def advisor_list() -> dict:
    advisors = [
        {"advisor_sid": sid,
         "advisor_name": str(a.get("advisor_name") or ""),
         "rep_code": str(a.get("rep_code") or ""),
         "in_cohort": a.get("in_cohort") is True}
        for sid, a in sorted(_store().all_vertices("phx_dm_pce_advisor").items())
    ]
    return {"advisors": advisors,
            "cohort_count": sum(1 for a in advisors if a["in_cohort"])}


# ------------------------------------------------------------------ summary

def _team_status(sid: str) -> dict:
    """Team / Individual from phx_dm_pce_team_agreement: the advisor appears
    in an ACTIVE agreement => Team, with the agreement's team rep code."""
    agreements = _catalog("team_members", {"advisor": sid})
    active = [a for a in agreements if a.get("status") == "ACTIVE"]
    team_rep = None
    if active:
        # team_rep_cd lives on the agreement vertex, not the catalog row
        vertices = _store().all_vertices("phx_dm_pce_team_agreement")
        ids = {a["agreement_id"] for a in active}
        for v in vertices.values():
            if str(v.get("agreement_id")) in ids:
                team_rep = str(v.get("team_rep_cd") or "") or None
                break
    return {"is_team": bool(active), "team_rep_cd": team_rep,
            "agreements": agreements}


@router.get("/{sid}/summary")
def advisor_summary(sid: str,
                    from_month: str = Query(..., alias="from"),
                    to_month: str = Query(..., alias="to")) -> dict:
    adv = _advisor_row(sid)
    months = _month_ids()
    for label, mid in (("from", from_month), ("to", to_month)):
        if mid not in months:
            raise HTTPException(404, f"unknown {label} month '{mid}'")

    # per-month AUM for the chart — null when the advisor holds no account
    # rows that month (honest, never 0-as-a-guess)
    aum_by_month: dict[str, float | None] = {}
    for mid in months:
        rows = _catalog("advisor_aum", {"advisor": sid, "month_id": mid})
        row = rows[0] if rows else None
        has_rows = any(str(r.get("advisor_sid")) == sid
                       and str(r.get("month_id")) == mid
                       for r in _store().all_vertices("phx_dm_pce_account_month").values())
        aum_by_month[mid] = row["total_balance"] if (row and has_rows) else None

    # lifecycle counts (Round A1 rule outcomes — includes Retained)
    life = _catalog("account_lifecycle_counts",
                    {"scope": sid, "from_month": from_month,
                     "to_month": to_month})[0]

    # AUM with prior-month delta
    aum_rows = _catalog("advisor_aum", {"advisor": sid, "month_id": to_month})
    aum = aum_rows[0] if aum_rows else None

    # Round 3 review D2/B1 — AUM is Managed Accounts only: summed end
    # balances of the advisor's accounts where the account master says
    # is_managed, for the to-month and its prior (null when no managed rows).
    def _managed_aum(month_id: str) -> float | None:
        managed = {k for k, a in _store().all_vertices("phx_dm_pce_account").items()
                   if a.get("is_managed") in (True, "True", "true", 1, "1")}
        rows = [r for r in _store().all_vertices("phx_dm_pce_account_month").values()
                if str(r.get("advisor_sid")) == sid
                and str(r.get("month_id")) == str(month_id)
                and str(r.get("acct_key")) in managed]
        if not rows:
            return None
        return round(sum(float(r.get("end_balance") or 0) for r in rows), 2)

    prior_mid = months[months.index(to_month) - 1] if months.index(to_month) > 0 else None
    managed_now = _managed_aum(to_month)
    managed_prior = _managed_aum(prior_mid) if prior_mid else None
    aum_managed = (None if managed_now is None else {
        "total_balance": managed_now,
        "prior_balance": managed_prior,
        "change_amt": (round(managed_now - managed_prior, 2)
                       if managed_prior is not None else None)})

    # NCF — Net CASH Flows for the to-month (review B3: renamed from the
    # mis-labelled 'net credited flows'; derivation verified — the flow
    # vertex's total_net_flows sums the source's total_net_financial_flows,
    # never a credited-revenue field; credited_flows is the separate column)
    flows_rows = _catalog("advisor_flows_summary",
                          {"advisor": sid, "month_id": to_month})
    ncf = flows_rows[0] if flows_rows else None

    # Round F2: the flows-proxy NNM block is GONE from this summary — the four
    # real NNM category files now load into phx_dm_pce_advisor_nnm and the
    # dedicated GET /api/advisor/{sid}/nnm endpoint serves the real figures
    # (latest-month YTD, threshold resolved from the extracted plan rule).
    # Net cash flows remain above as NCF, which is what the flow table
    # actually measures.

    # trades per month for this advisor (the months query's txn_count)
    from app.graph.client import get_graph_client

    month_rows = (get_graph_client()
                  .run_query("pce_dashboard_months", {"advisor": sid})
                  .get("results") or [{}])[0].get("months", [])
    trades = {m["month_id"]: m.get("txn_count", 0) for m in month_rows}

    return {
        "advisor": {"advisor_sid": sid,
                    "advisor_name": str(adv.get("advisor_name") or ""),
                    "rep_code": str(adv.get("rep_code") or ""),
                    "in_cohort": adv.get("in_cohort") is True},
        "team": _team_status(sid),
        "from": from_month, "to": to_month,
        "aum_by_month": aum_by_month,
        "metrics": {
            "lifecycle": {"new_count": life["new_count"],
                          "lost_count": life["lost_count"],
                          "retained_count": life["retained_count"],
                          "notes": life.get("notes") or ""},
            "aum": ({"total_balance": aum["total_balance"],
                     "prior_balance": aum["prior_balance"],
                     "change_amt": aum["change_amt"]} if aum else None),
            # Round 3 D2/B1 — the UI's AUM tile renders THIS, labelled
            # "AUM (Managed Accounts only)"; the all-accounts figure above
            # stays for API compatibility.
            "aum_managed": aum_managed,
            "ncf": ({"net_flows": ncf["net_flows"], "inflows": ncf["inflows"],
                     "outflows": ncf["outflows"],
                     "credited_flows": ncf["credited_flows"]} if ncf else None),
            "trades": {"from_count": trades.get(from_month, 0),
                       "to_count": trades.get(to_month, 0),
                       "delta": trades.get(to_month, 0) - trades.get(from_month, 0)},
        },
    }


# ------------------------------------------------------------- peer ranking

def _rank_block(sid: str, values: dict[str, float | None]) -> dict:
    """Rank descending over non-null values; median over the ranked set."""
    from statistics import median

    ranked = sorted(((s, v) for s, v in values.items() if v is not None),
                    key=lambda kv: -kv[1])
    med = round(median(v for _s, v in ranked), 2) if ranked else None
    rank = next((i + 1 for i, (s, _v) in enumerate(ranked) if s == sid), None)
    return {"rank": rank, "cohort_size": len(ranked),
            "value": values.get(sid), "cohort_median": med}


def _peer_ranking(sid: str, from_month: str, to_month: str) -> dict:
    _advisor_row(sid)
    cohort = {s for s, a in _store().all_vertices("phx_dm_pce_advisor").items()
              if a.get("in_cohort") is True}

    rev_to = {r["advisor_sid"]: r["value"] for r in _catalog(
        "cohort_ranking", {"advisor": "all", "month_id": to_month,
                           "metric": "credited_amt"})}
    rev_from = {r["advisor_sid"]: r["value"] for r in _catalog(
        "cohort_ranking", {"advisor": "all", "month_id": from_month,
                           "metric": "credited_amt"})}
    growth = {s: round(rev_to.get(s, 0.0) - rev_from.get(s, 0.0), 2)
              for s in cohort}

    # discount rate: mean fee reduction across the advisor's rate-bearing
    # accounts in the to-month (threshold -1 => every rate-bearing account);
    # advisors with no rate-bearing accounts are null, excluded from the rank
    discount: dict[str, float | None] = {}
    for s in cohort:
        accounts = _catalog("fee_reduction_accounts",
                            {"advisor": s, "month_id": to_month,
                             "threshold_pct": -1})
        discount[s] = (round(sum(a["reduction_pct"] for a in accounts)
                             / len(accounts), 2) if accounts else None)

    return {
        "advisor_sid": sid, "from": from_month, "to": to_month,
        "revenue": _rank_block(sid, {s: rev_to.get(s, 0.0) for s in cohort}),
        "growth": _rank_block(sid, growth),
        "discount_rate": {
            **_rank_block(sid, discount),
            "note": ("mean fee reduction %% across rate-bearing accounts in "
                     f"{to_month}; advisors with no rate-bearing accounts are "
                     "excluded"),
        },
    }


@router.get("/{sid}/peer-ranking",
            dependencies=[Depends(require_feature("advisor.peer_ranking"))])
def peer_ranking(sid: str, from_month: str = Query(..., alias="from"),
                 to_month: str = Query(..., alias="to")) -> dict:
    return _peer_ranking(sid, from_month, to_month)


# ----------------------------------------------------------------- coaching

def _coach_facts(sid: str, from_month: str, to_month: str) -> dict:
    """The deterministic facts the Coach may cite — peer ranks, discount rate,
    lifecycle counts, flows. Computed here, passed into the prompt."""
    ranking = _peer_ranking(sid, from_month, to_month)
    life = _catalog("account_lifecycle_counts",
                    {"scope": sid, "from_month": from_month,
                     "to_month": to_month})[0]
    return {
        "advisor_sid": sid, "transition": f"{from_month}->{to_month}",
        "peer_ranks": {
            "revenue": ranking["revenue"],
            "growth": ranking["growth"],
            "discount_rate": {k: ranking["discount_rate"][k]
                              for k in ("rank", "cohort_size", "value",
                                        "cohort_median")},
        },
        "lifecycle": {"new_accounts": life["new_count"],
                      "lost_accounts": life["lost_count"],
                      "retained_accounts": life["retained_count"]},
        "net_flows": life.get("net_flows"),
    }


@router.post("/{sid}/coaching/generate",
             dependencies=[Depends(require_feature("advisor.coaching"))])
def coaching_generate(sid: str, from_month: str = Query(..., alias="from"),
                      to_month: str = Query(..., alias="to")) -> dict:
    from app.agents.coach import generate_coaching

    _advisor_row(sid)
    facts = _coach_facts(sid, from_month, to_month)
    return generate_coaching(sid, from_month, to_month, facts)


@router.get("/{sid}/coaching",
            dependencies=[Depends(require_feature("advisor.coaching"))])
def coaching_get(sid: str, from_month: str = Query(..., alias="from"),
                 to_month: str = Query(..., alias="to")) -> dict:
    from app.agents.coach import get_coach_store

    _advisor_row(sid)
    stored = get_coach_store().get(sid, from_month, to_month)
    if stored is None:
        return {"generated": False, "advisor_sid": sid,
                "from_month": from_month, "to_month": to_month,
                "points": [], "note": "no coaching generated yet"}
    return {"generated": True, **stored}


# ------------------------------------------------------------ opportunities

ASSUMPTION_NOTE = ("Amount is the forecast pipeline value; Actual assets is what "
                   "landed — working interpretation until the client confirms. "
                   "The two are never summed.")
WON_LOST_NOTE = ("The source CRM carries no Won/Lost stage; stage groups are "
                 "shown instead and no outcome is invented.")


@router.get("/{sid}/opportunities",
            dependencies=[Depends(require_feature("advisor.crm_opportunities"))])
def opportunities(sid: str,
                  from_month: str | None = Query(None, alias="from"),
                  to_month: str | None = Query(None, alias="to")) -> dict:
    """Round F2: the real CRM extract shape. Three provenances ride every
    detail row — source stage, verbatim comment, labelled AI reading. The
    reading is descriptive only: nothing here aggregates, filters or sorts on
    it (rows sort on is_stalled then actual_assets — source data)."""
    from app.agents.coach import get_coach_store

    _advisor_row(sid)
    groups = _catalog("advisor_pipeline", {"advisor": sid})
    rows = _catalog("advisor_opportunity_detail", {"advisor": sid})
    invalid = sum(1 for r in rows if r.get("advisor_valid") is False)
    guidance = None
    if from_month and to_month:
        stored = get_coach_store().get(sid, from_month, to_month)
        if stored:
            guidance = stored.get("opportunities_guidance")
    return {
        "advisor_sid": sid,
        "by_stage_group": [{k: g.get(k) for k in
                            ("stage_group", "opportunity_count", "forecast_amount",
                             "actual_assets", "stalled_count")} for g in groups],
        "opportunities": rows,
        "data_quality": {"invalid_advisor_rows": invalid,
                         **({"note": "invalid advisor references exist in the "
                                     "source and are shown, not hidden"}
                            if invalid else {})},
        "assumption_note": ASSUMPTION_NOTE,
        "won_lost_note": WON_LOST_NOTE,
        "guidance": guidance,
    }

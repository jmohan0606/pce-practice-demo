"""Cost & Trace API (cost-fix session task 3).

GET /api/trace/runs            — one row per turn-logged scope (insight runs +
                                 the synthetic doc_extract| / conflict_audit| scopes)
GET /api/trace/runs/{run_id}   — per-turn table for one scope
GET /api/trace/summary         — totals per advisor / document extraction /
                                 full refresh, plus the projection inputs the
                                 Generate buttons show before a run

Costs and tokens come from phx_dm_pce_agent_turn_log rows (response.usage —
never estimated); the projection is an average of previous completed runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.flags.registry import require_feature
from app.insights.store import get_insight_store

router = APIRouter(prefix="/api/trace", tags=["trace"],
                   # Round A2B task 7: OFF means these queries do not run
                   dependencies=[Depends(require_feature("global.trace"))])


def _totals(turns: list[dict]) -> dict:
    input_t = sum(t["input_tokens"] for t in turns)
    output_t = sum(t["output_tokens"] for t in turns)
    cache_read = sum(t["cache_read_tokens"] for t in turns)
    cache_write = sum(t["cache_write_tokens"] for t in turns)
    prompt_total = input_t + cache_read + cache_write
    return {
        "turns": len(turns),
        "input_tokens": input_t,
        "output_tokens": output_t,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cache_hit_pct": round(cache_read / prompt_total * 100, 1) if prompt_total else 0.0,
        "est_cost_usd": round(sum(t["est_cost_usd"] for t in turns), 6),
    }


def _run_row(run_id: str, run: dict | None, turns: list[dict]) -> dict:
    import json as _json

    totals = _totals(turns)
    if run is not None:
        limits = _json.loads(run.get("limits_json") or "[]")
        scope = {
            "kind": "insight_run", "advisor_sid": run["advisor_sid"],
            "transition": f"{run['from_month_id']} → {run['to_month_id']}",
            "version_id": run["version_id"], "status": run["status"],
            "query_count": run.get("query_count", 0),
            "wall_ms": run.get("wall_ms", 0),
            "budget_hit": bool(run.get("budget_hit")),
            "budget_hit_tokens": bool(run.get("budget_hit_tokens")),
            # Round H 2.3/4.2: the Limits column — every bound limit with its
            # name, value and effect; a run that hit a limit is visually
            # distinct from one that finished clean.
            "limit_hit": bool(limits),
            "limits_hit": limits,
            "started_at": run.get("started_at"),
        }
    else:
        kind = ("document_extraction" if run_id.startswith("doc_extract|")
                else "conflict_audit" if run_id.startswith("conflict_audit|")
                # Round E task 7: chat turns are logged under chat|<conversation_id>
                else "chat" if run_id.startswith("chat|")
                else "other")
        scope = {"kind": kind, "advisor_sid": None, "transition": None,
                 "version_id": None, "status": "LOGGED", "query_count": 0,
                 "wall_ms": sum(t["latency_ms"] for t in turns),
                 "budget_hit": False, "budget_hit_tokens": False,
                 "limit_hit": False, "limits_hit": [],
                 "started_at": None}
    return {"run_id": run_id, **scope, **totals}


@router.get("/runs")
def runs() -> dict:
    store = get_insight_store()
    turn_logs = store.all_turn_logs()
    rows = []
    seen = set()
    for run_id, turns in turn_logs.items():
        rows.append(_run_row(run_id, store.run(run_id), turns))
        seen.add(run_id)
    # insight runs that never made an LLM call (e.g. failed before turn 1)
    for run_id in store.runs:
        if run_id not in seen:
            rows.append(_run_row(run_id, store.run(run_id), []))
    rows.sort(key=lambda r: (r["started_at"] or "", r["run_id"]), reverse=True)
    return {"runs": rows}


@router.get("/guardrail")
def guardrail(tag: str | None = None) -> dict:
    """Round E task 7 — the Guardrail tab's feed. Every classification ever
    made, blocked or not (the log is what demos Layer 1; the tools_called
    column — 0 for anything blocked outright — is what demos Layer 2).

    ``summary`` and ``total`` always cover the full log; ``?tag=`` filters
    ``rows`` only, so the count chips stay stable while filtering.
    """
    from app.chat.store import get_chat_store

    all_rows = get_chat_store().guardrail_log()
    summary: dict[str, int] = {}
    for r in all_rows:
        summary[r["tag"]] = summary.get(r["tag"], 0) + 1
    rows = [r for r in all_rows if r["tag"] == tag] if tag else all_rows
    return {"rows": rows, "summary": summary, "total": len(all_rows)}


@router.get("/alltime")
def alltime() -> dict:
    """All-time totals since inception (Round E task 7): every turn-logged
    scope in the store. Cache READ and cache WRITE are reported separately —
    one combined number hid a run that wrote 1.5x more than it read."""
    store = get_insight_store()
    turn_logs = store.all_turn_logs()
    all_turns = [t for turns in turn_logs.values() for t in turns]
    run_ids = set(turn_logs) | set(store.runs)
    started = [r.get("started_at") for r in
               (store.run(rid) for rid in store.runs) if r and r.get("started_at")]
    return {
        **_totals(all_turns),
        "total_runs": len(run_ids),
        "total_llm_ms": sum(t["latency_ms"] for t in all_turns),
        "since": min(started) if started else None,
    }


@router.get("/summary")
def summary() -> dict:
    from app.config.settings import get_settings
    from app.llm.pricing import estimate_cost_no_cache_usd

    store = get_insight_store()
    turn_logs = store.all_turn_logs()
    # Round H task 3.3: when ASSUME_PROMPT_CACHING=false (the operator measured
    # that the provider caches nothing — scripts/check_cache_support.py), the
    # projection reprices every historical prompt token at the FULL input rate;
    # logged actuals (est_cost_usd) are never rewritten.
    assume_caching = get_settings().assume_prompt_caching

    def _projected_run_cost(turns: list[dict]) -> float:
        if assume_caching:
            return sum(t["est_cost_usd"] for t in turns)
        return sum(estimate_cost_no_cache_usd(
            t["model"], t["input_tokens"], t["output_tokens"],
            t["cache_read_tokens"], t["cache_write_tokens"]) for t in turns)

    per_advisor: dict[str, list[dict]] = {}
    extraction_turns: list[dict] = []
    audit_turns: list[dict] = []
    compile_turns: list[dict] = []
    compile_run_count = 0
    completed_costs: list[float] = []
    completed_walls: list[int] = []
    for run_id, turns in turn_logs.items():
        run = store.run(run_id)
        if run is not None:
            per_advisor.setdefault(run["advisor_sid"], []).extend(turns)
            if run["status"] == "COMPLETE" and turns:
                completed_costs.append(_projected_run_cost(turns))
                completed_walls.append(int(run.get("wall_ms") or 0))
        elif run_id.startswith("doc_extract|"):
            extraction_turns.extend(turns)
        elif run_id.startswith("conflict_audit|"):
            audit_turns.extend(turns)
        elif run_id.startswith(("rule_compile|", "rule_preview|")):
            # Round 7 task 9 — measured compile costs feed the Preview
            # button's honest estimate
            compile_turns.extend(turns)
            compile_run_count += 1
    history = len(completed_costs)
    avg_cost = (sum(completed_costs) / history) if history else None
    avg_wall_ms = (sum(completed_walls) / history) if history else None
    # a "full refresh" = the all-advisors batch: aggregate book + every cohort advisor
    from app.insights.service import cohort_advisors

    try:
        refresh_runs = len(cohort_advisors()) + 1
    except Exception:  # noqa: BLE001 — graph unavailable: no projection
        refresh_runs = None
    return {
        "per_advisor": [{"advisor_sid": sid, **_totals(turns)}
                        for sid, turns in sorted(per_advisor.items())],
        "document_extraction": _totals(extraction_turns),
        "conflict_audit": _totals(audit_turns),
        "rule_compile": {
            **_totals(compile_turns),
            "run_count": compile_run_count,
            "avg_cost_usd": (round(_totals(compile_turns)["est_cost_usd"]
                                   / compile_run_count, 4)
                             if compile_run_count else None),
        },
        "full_refresh": {
            "run_count": refresh_runs,
            "est_cost_usd": (round(avg_cost * refresh_runs, 4)
                             if avg_cost is not None and refresh_runs else None),
            "est_minutes": (round(avg_wall_ms * refresh_runs / 60000, 1)
                            if avg_wall_ms is not None and refresh_runs else None),
        },
        "projection": {
            "assume_prompt_caching": assume_caching,
            "history_runs": history,
            "avg_run_cost_usd": round(avg_cost, 4) if avg_cost is not None else None,
            "avg_run_wall_ms": int(avg_wall_ms) if avg_wall_ms is not None else None,
        },
    }


@router.get("/runs/{run_id:path}")
def run_detail(run_id: str) -> dict:
    store = get_insight_store()
    turns = store.run_turn_log(run_id)
    run = store.run(run_id)
    if not turns and run is None:
        raise HTTPException(404, f"no trace for '{run_id}'")
    return {
        **_run_row(run_id, run, turns),
        "turn_rows": [{
            "seq_no": t["seq_no"], "agent_name": t["agent_name"],
            "action_kind": t["action_kind"], "query_name": t["query_name"],
            "model": t["model"], "input_tokens": t["input_tokens"],
            "output_tokens": t["output_tokens"],
            "cache_read_tokens": t["cache_read_tokens"],
            "cache_write_tokens": t["cache_write_tokens"],
            "latency_ms": t["latency_ms"], "est_cost_usd": t["est_cost_usd"],
        } for t in turns],
    }

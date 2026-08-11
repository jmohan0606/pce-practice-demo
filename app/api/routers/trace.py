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

from fastapi import APIRouter, HTTPException

from app.insights.store import get_insight_store

router = APIRouter(prefix="/api/trace", tags=["trace"])


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
    totals = _totals(turns)
    if run is not None:
        scope = {
            "kind": "insight_run", "advisor_sid": run["advisor_sid"],
            "transition": f"{run['from_month_id']} → {run['to_month_id']}",
            "version_id": run["version_id"], "status": run["status"],
            "query_count": run.get("query_count", 0),
            "wall_ms": run.get("wall_ms", 0),
            "budget_hit": bool(run.get("budget_hit")),
            "budget_hit_tokens": bool(run.get("budget_hit_tokens")),
            "started_at": run.get("started_at"),
        }
    else:
        kind = ("document_extraction" if run_id.startswith("doc_extract|")
                else "conflict_audit" if run_id.startswith("conflict_audit|")
                else "other")
        scope = {"kind": kind, "advisor_sid": None, "transition": None,
                 "version_id": None, "status": "LOGGED", "query_count": 0,
                 "wall_ms": sum(t["latency_ms"] for t in turns),
                 "budget_hit": False, "budget_hit_tokens": False,
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


@router.get("/summary")
def summary() -> dict:
    store = get_insight_store()
    turn_logs = store.all_turn_logs()
    per_advisor: dict[str, list[dict]] = {}
    extraction_turns: list[dict] = []
    audit_turns: list[dict] = []
    completed_costs: list[float] = []
    completed_walls: list[int] = []
    for run_id, turns in turn_logs.items():
        run = store.run(run_id)
        if run is not None:
            per_advisor.setdefault(run["advisor_sid"], []).extend(turns)
            if run["status"] == "COMPLETE" and turns:
                completed_costs.append(sum(t["est_cost_usd"] for t in turns))
                completed_walls.append(int(run.get("wall_ms") or 0))
        elif run_id.startswith("doc_extract|"):
            extraction_turns.extend(turns)
        elif run_id.startswith("conflict_audit|"):
            audit_turns.extend(turns)
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
        "full_refresh": {
            "run_count": refresh_runs,
            "est_cost_usd": (round(avg_cost * refresh_runs, 4)
                             if avg_cost is not None and refresh_runs else None),
            "est_minutes": (round(avg_wall_ms * refresh_runs / 60000, 1)
                            if avg_wall_ms is not None and refresh_runs else None),
        },
        "projection": {
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

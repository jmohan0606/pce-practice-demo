"""Round A2B task 7 — the feature-flags API.

GET   /api/flags                 every flag with state, notes and cost hints
PATCH /api/flags/{key}           {enabled, reason?, by?} — 400 without a reason
                                 when turning off; 400 on the guardrail
POST  /api/flags/preset/{name}   full | client_demo | minimal
GET   /api/flags/history         every change: flag, on/off, who, when, reason

Cost hints come from /api/trace/summary-style averages over the agent turn log
— never hardcoded where trace data exists. The chat figure is a static
"estimate, feature not built" string by design (there is no data to average).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.flags.registry import FLAGS, PRESETS
from app.flags.store import FlagStoreError, get_flag_store

router = APIRouter(prefix="/api/flags", tags=["flags"])

_DRILLDOWN_PREFIXES = ("product|", "product_advisor|", "product_account|")


def _avg_completed_run_cost(filter_fn) -> tuple[float | None, int]:
    """Average est cost across completed turn-logged runs passing filter_fn."""
    from app.insights.store import get_insight_store

    store = get_insight_store()
    costs = []
    for run_id, turns in store.all_turn_logs().items():
        if not turns or not filter_fn(run_id):
            continue
        run = store.run(run_id)
        if run is not None and run.get("status") != "COMPLETE":
            continue
        costs.append(sum(t["est_cost_usd"] for t in turns))
    return (round(sum(costs) / len(costs), 4) if costs else None), len(costs)


def _cost_hints() -> dict[str, dict | None]:
    """kind -> serialized hint. None amount = "no runs yet — cost unknown"."""
    ins_avg, ins_n = _avg_completed_run_cost(
        lambda rid: not rid.startswith(_DRILLDOWN_PREFIXES)
        and not rid.startswith(("coach|", "doc_extract|", "conflict_audit|")))
    dd_avg, dd_n = _avg_completed_run_cost(
        lambda rid: rid.startswith(_DRILLDOWN_PREFIXES))
    coach_avg, coach_n = _avg_completed_run_cost(
        lambda rid: rid.startswith("coach|"))
    return {
        "insights_avg": {"amount_usd": ins_avg, "unit": "per transition",
                         "history_runs": ins_n, "note": None},
        "drilldown_avg": {"amount_usd": dd_avg, "unit": "per drill-down",
                          "history_runs": dd_n, "note": None},
        "coach_avg": {"amount_usd": coach_avg, "unit": "per advisor",
                      "history_runs": coach_n, "note": None},
        # static by design: an estimate label, not a definition — no data exists
        "chat_static": {"amount_usd": 0.02, "unit": "per message",
                        "history_runs": 0,
                        "note": "estimate, feature not built"},
    }


def _serialize(rows: list[dict]) -> dict:
    hints = _cost_hints()
    out = []
    for row in rows:
        cost_kind = row.pop("cost")
        out.append({**row, "cost": hints.get(cost_kind) if cost_kind else None})
    return {"flags": out,
            "on_count": sum(1 for r in out if r["enabled"]),
            "total": len(out), "ceiling": 30,
            "groups": [{"id": gid, "name": name}
                       for gid, name in
                       (("dashboard", "Practice Management Dashboard"),
                        ("advisor", "iPerform Advisor AI Insights"),
                        ("docs", "Documents & Rules"),
                        ("rules", "Rule Versions"),
                        ("global", "Global"))],
            "presets": [{"id": pid, "name": p["name"],
                         "description": p["description"],
                         "on_count": len(FLAGS) - len(p["off"]),
                         "total": len(FLAGS)}
                        for pid, p in PRESETS.items()]}


@router.get("")
def get_flags() -> dict:
    return _serialize(get_flag_store().snapshot())


class PatchFlag(BaseModel):
    enabled: bool
    reason: str | None = None
    by: str | None = None


@router.patch("/{key:path}")
def patch_flag(key: str, body: PatchFlag) -> dict:
    if key not in FLAGS:
        raise HTTPException(404, f"unknown feature flag '{key}'")
    try:
        row = get_flag_store().set_flag(
            key, body.enabled, by=(body.by or "operator").strip() or "operator",
            reason=body.reason or "")
    except FlagStoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    hints = _cost_hints()
    cost_kind = row.pop("cost")
    return {**row, "cost": hints.get(cost_kind) if cost_kind else None}


@router.post("/preset/{name}")
def apply_preset(name: str, body: dict | None = None) -> dict:
    try:
        rows = get_flag_store().apply_preset(
            name, by=str((body or {}).get("by") or "operator"))
    except FlagStoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _serialize(rows)


@router.get("/history")
def history() -> dict:
    return {"history": get_flag_store().history()}

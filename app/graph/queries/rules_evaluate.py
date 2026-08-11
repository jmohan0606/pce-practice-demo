"""Mock-tier implementation of the rules_evaluate_plan query (B3 Rules track).

Registered via @mock_query so rule evaluation goes through the tiered graph
client like every other catalogued query; the local store serves it in mock
mode (and as the tier-4 fallback in real modes until a GSQL equivalent is
installed on a live TigerGraph).

Params: {"plan": <compiled query plan>, "params": {month, advisor_sid,
exclude_keys, ...}}. Returns one result row — the evaluator's
{matched, matched_count, evaluated_rows, empty_reason?} dict.
"""
from __future__ import annotations

from app.graph.client import mock_query
from app.graph.foundation_store import FoundationGraphStore


@mock_query("rules_evaluate_plan")
def rules_evaluate_plan(store: FoundationGraphStore, params: dict) -> list[dict]:
    from app.rules.evaluator import evaluate_plan  # local import: no cycle at module load

    plan = params.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("rules_evaluate_plan requires a 'plan' dict parameter")
    return [evaluate_plan(store, plan, params.get("params") or {})]

#!/usr/bin/env python3
"""Round 10 task 5 — the rule_evaluation_rows OUTPUT CONTRACT test, asserted
against a NON-MOCK payload.

Round 9's C6-1 asserted the {__vertex_id, <columns>} contract by calling the
mock-tier Python implementation — a test the GSQL twin could never fail, and
it didn't catch the twin returning bare vertex-set PRINT wrappers the caller
cannot read. This script tests the twin ITSELF:

1. parses docs/tigergraph/queries/rule_evaluation_rows.gsql — branch guards,
   PRINT form, projection aliases;
2. DRIFT CHECK: the twin's branch set must equal RULE_EVALUATION_VERTICES
   (the one supported-types source in app/graph/queries/catalog.py);
3. every branch must PRINT a bracketed projection whose aliases include
   __vertex_id and cover every schema attribute — a bare `PRINT rows_x;`
   FAILS here by name;
4. simulates the REAL-TIER payload the twin produces (TigerGraph PRINT
   wrappers: one object per PRINT, entries as {v_id, v_type, attributes:
   {alias: value}} built from the PARSED aliases — the fixture is the shape
   TigerGraph returns, never the mock implementation's output) and runs it
   through the actual caller path: a fake tier-2 client behind
   run_catalog_query. Asserts flat rows, __vertex_id at the top level, and
   the columns projection applied;
5. end-to-end: the same compiled rule plan evaluated on the mock tier and on
   the simulated real tier must produce IDENTICAL matched rows;
6. self-probe: a bare-PRINT payload (no aliases, attributes nested raw) must
   be REFUSED by _normalize_rule_evaluation_rows — proving the failure mode
   stays loud.

If the twin reverts to a bare PRINT in any branch, checks 3-5 fail naming it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TWIN = ROOT / "docs" / "tigergraph" / "queries" / "rule_evaluation_rows.gsql"

FAILURES: list[str] = []


def check(no: int, title: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  RR-{no}. {title} — {detail}")
    if not ok:
        FAILURES.append(title)


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def parse_twin() -> dict[str, dict]:
    """branch vertex type -> {"set": rows_<x>, "print": "bracketed"|"bare"|None,
    "aliases": {alias: source_attr}}"""
    src = strip_comments(TWIN.read_text(encoding="utf-8"))
    branches: dict[str, dict] = {}
    for m in re.finditer(r"(rows_\w+)\s*=\s*SELECT\s+\w+\s+FROM[^;]*?"
                         r"vertex_type\s*==\s*\"([\w.]+)\"", src, re.S):
        branches[m.group(2)] = {"set": m.group(1), "print": None, "aliases": {}}
    sets = {b["set"]: vt for vt, b in branches.items()}
    for m in re.finditer(r"PRINT\s+(rows_\w+)\s*(\[(.*?)\])?\s*;", src, re.S):
        setname, bracket = m.group(1), m.group(3)
        vt = sets.get(setname)
        if vt is None:
            continue
        if bracket is None:
            branches[vt]["print"] = "bare"
            continue
        aliases = {}
        for item in bracket.split(","):
            am = re.search(rf"{setname}\.(\w+)\s+AS\s+(\w+)", item)
            if am:
                aliases[am.group(2)] = am.group(1)
        branches[vt]["print"] = "bracketed"
        branches[vt]["aliases"] = aliases
    return branches


def simulate_payload(branches: dict, vertex_type: str, params: dict) -> list[dict]:
    """The TigerGraph payload for one call — built from the twin's PARSED
    print form, with row VALUES from the mock store (the twin's WHERE
    semantics are pinned identical elsewhere; this fixture pins the SHAPE)."""
    from app.graph.client import MOCK_QUERY_IMPLS
    from app.graph.foundation_store import get_foundation_store

    impl = MOCK_QUERY_IMPLS["rule_evaluation_rows"]
    full_rows = impl(get_foundation_store(),
                     {k: v for k, v in params.items() if k != "columns"})
    payload = []
    for vt, branch in branches.items():
        entries = []
        if vt == vertex_type:
            for row in full_rows:
                if branch["print"] == "bracketed":
                    attributes = {alias: (row.get("__vertex_id")
                                          if src_attr == "__vertex_id" or alias == "__vertex_id"
                                          and src_attr not in row else row.get(src_attr))
                                  for alias, src_attr in branch["aliases"].items()}
                    # alias __vertex_id sources the pid attribute — same value
                    if "__vertex_id" in branch["aliases"]:
                        attributes["__vertex_id"] = row["__vertex_id"]
                else:  # bare PRINT: raw attributes, NO aliases, NO __vertex_id
                    attributes = {k: v for k, v in row.items() if k != "__vertex_id"}
                entries.append({"v_id": row["__vertex_id"], "v_type": vt,
                                "attributes": attributes})
        payload.append({branch["set"]: entries})
    return payload


class FakeRealTier:
    """Tier-2 stand-in: succeeds, returns the simulated TigerGraph payload."""

    def __init__(self, branches: dict) -> None:
        self.branches = branches

    def run_query(self, query_name: str, params: dict | None = None) -> dict:
        assert query_name == "rule_evaluation_rows", query_name
        payload = simulate_payload(self.branches, str(params["vertex_type"]),
                                   dict(params or {}))
        return {"error": False, "results": payload, "mode": "pytigergraph",
                "query": query_name, "served_by_tier": 2}


def main() -> int:  # noqa: PLR0915 — one linear check script
    import app.graph.client as client_mod
    from app.graph.queries.catalog import (
        RULE_EVALUATION_VERTICES,
        _normalize_rule_evaluation_rows,
        run_catalog_query,
    )
    from app.rules.compiler import load_schema_catalog

    branches = parse_twin()

    # 1 — drift: the twin's branch set == RULE_EVALUATION_VERTICES
    twin_types = set(branches)
    check(1, "twin branch set equals RULE_EVALUATION_VERTICES (one source)",
          twin_types == set(RULE_EVALUATION_VERTICES),
          f"twin={len(twin_types)} constant={len(RULE_EVALUATION_VERTICES)}; "
          f"diff={sorted(twin_types ^ set(RULE_EVALUATION_VERTICES)) or 'none'}")

    # 2 — every branch prints a bracketed projection with __vertex_id and
    #     full attribute coverage
    schema = load_schema_catalog()["vertices"]
    bad_print = [vt for vt, b in branches.items() if b["print"] != "bracketed"]
    missing_vid = [vt for vt, b in branches.items()
                   if b["print"] == "bracketed" and "__vertex_id" not in b["aliases"]]
    missing_attrs = {vt: sorted(set(schema[vt]["attributes"]) - set(b["aliases"]))
                     for vt, b in branches.items() if b["print"] == "bracketed"}
    missing_attrs = {vt: miss for vt, miss in missing_attrs.items() if miss}
    check(2, "every branch PRINTs a bracketed projection with __vertex_id "
             "covering every schema attribute",
          not bad_print and not missing_vid and not missing_attrs,
          f"bare/missing PRINT={bad_print or 'none'}; "
          f"no __vertex_id alias={missing_vid or 'none'}; "
          f"attribute gaps={missing_attrs or 'none'}")

    # 3 — the simulated REAL payload flows through the actual caller path and
    #     lands flat, keyed, projected
    from app.rules.compiler import translate_plan
    from app.rules.evaluator import evaluate_plan

    plan_json = {
        "vertex": "phx_dm_pce_revenue_transaction",
        "filters": [{"field": "reason_cd", "op": "=", "value": "9E"}],
        "compute": {"agg": "sum", "expr": "non_credited_amt"},
        "trigger": {"op": ">", "value": -1e18},
        "attribute": None, "params": [], "group_by": None}
    compiled = translate_plan("CONTRACT_PROBE", "month", plan_json)

    fake = FakeRealTier(branches)
    original = client_mod._graph_client
    client_mod._graph_client = fake
    try:
        try:
            out = run_catalog_query(
                "rule_evaluation_rows",
                {"vertex_type": "phx_dm_pce_month", "columns": "month_name"},
                allow_internal=True)
            rows = out["rows"]
            ok = bool(rows) and all(set(r) == {"__vertex_id", "month_name"}
                                    for r in rows)
            detail = (f"row keys={sorted(rows[0]) if rows else 'NO ROWS'}; "
                      f"rows={len(rows)}")
        except Exception as exc:  # noqa: BLE001 — a raise IS the failure, named
            ok, detail = False, f"caller path REFUSED the payload: {str(exc)[:110]}"
        check(3, "simulated real-tier payload arrives FLAT with __vertex_id, "
                 "columns projection applied", ok, detail)

        # 4 — same rule, mock tier vs simulated real tier: identical matched
        try:
            real_out = evaluate_plan(None, compiled.plan, {"month": "202605"})
        except Exception as exc:  # noqa: BLE001
            real_out = {"matched": f"RAISED: {str(exc)[:90]}", "evaluated_rows": -1}
    finally:
        client_mod._graph_client = original
    mock_out = evaluate_plan(None, compiled.plan, {"month": "202605"})
    check(4, "identical matched rows on the mock tier and the simulated real tier",
          real_out["matched"] == mock_out["matched"] and bool(mock_out["matched"])
          and real_out["evaluated_rows"] == mock_out["evaluated_rows"],
          f"mock={mock_out['matched']} | simulated-real={real_out['matched']}")

    # 5 — self-probe: a BARE-PRINT payload must be refused, never patched up
    bare_payload = [{"rows_month": [
        {"v_id": "202604", "v_type": "phx_dm_pce_month",
         "attributes": {"month_id": "202604", "month_name": "Apr 2026"}}]}]
    try:
        _normalize_rule_evaluation_rows(bare_payload, {"columns": "month_name"})
        refused = False
        detail = "bare payload was ACCEPTED (contract hole)"
    except RuntimeError as exc:
        refused = "__vertex_id" in str(exc)
        detail = f"refused: {str(exc)[:90]}…"
    check(5, "a bare-PRINT payload (no __vertex_id alias) is REFUSED loudly",
          refused, detail)

    print(f"\n{5 - len(FAILURES)}/5 checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

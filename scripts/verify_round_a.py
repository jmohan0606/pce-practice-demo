"""Round A verification — prints PASS/FAIL per check, exit 1 on any FAIL.

Checks (BUILD_PLAN §4 "done when"):
  1. every ported module imports
  2. GSQL DDL structure (24 vertices, 36 edges, reverse drop order, QUOTE="double")
  3. product model resolves per spec (sub-code splits, unmapped fallback)
  4. mock data CSV row counts match data/manifest.json exactly
  5. graph load: loaded counts match the manifest (via the graph client)
  6. monthly totals recomputed INDEPENDENTLY from the transaction CSV match the
     monthly_revenue aggregate vertices; credited excludes reason-coded rows
  7. scenario coverage present in the data
  8. GET /api/health returns green (graph healthy + vertex counts)

Run: python3 scripts/verify_round_a.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# 1 — imports
def check_imports() -> None:
    modules = [
        "app.config.settings", "app.shared.ids", "app.shared.logging", "app.shared.responses",
        "app.api.main", "app.api.middleware.correlation", "app.api.middleware.error_handlers",
        "app.graph.client", "app.graph.tiered_client", "app.graph.foundation_store", "app.graph.tier_log",
        "app.ingestion.ingestion_service", "app.ingestion.entity_registry", "app.ingestion.manifest_check",
        "app.llm.client", "app.llm.roles", "app.llm.embedding_client",
        "app.knowledge.knowledge_service", "app.knowledge.rag_service",
        "app.revenue.products", "app.revenue.aggregation",
    ]
    failed = []
    for m in modules:
        try:
            __import__(m)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{m}: {exc}")
    check("1. ported modules import", not failed, "; ".join(failed) or f"{len(modules)} modules")


# 2 — DDL structure
def check_ddl() -> None:
    tg = ROOT / "docs" / "tigergraph"
    v = (tg / "01_vertices.gsql").read_text(encoding="utf-8")
    e = (tg / "02_edges.gsql").read_text(encoding="utf-8")
    d = (tg / "90_drop_all.gsql").read_text(encoding="utf-8")
    vertices = re.findall(r"CREATE VERTEX (\w+)", v)
    edges = re.findall(r"CREATE DIRECTED EDGE (\w+)", e)
    drop_edges = re.findall(r"DROP EDGE (\w+)", d)
    drop_vertices = re.findall(r"DROP VERTEX (\w+)", d)
    check("2a. 24 vertices in 01_vertices.gsql", len(vertices) == 24, f"found {len(vertices)}")
    check("2b. 36 edges in 02_edges.gsql", len(edges) == 36, f"found {len(edges)}")
    check("2c. drop order is exact reverse of create order",
          drop_edges == list(reversed(edges)) and drop_vertices == list(reversed(vertices)))
    loads = 0
    quoted = 0
    for job in sorted((tg / "loading").glob("*.gsql")):
        text = job.read_text(encoding="utf-8")
        loads += len(re.findall(r"\bLOAD\b", text))
        quoted += text.count('QUOTE="double"')
    check('2d. QUOTE="double" on every LOAD', loads > 0 and loads == quoted, f"{quoted}/{loads} LOADs")
    catalog = json.loads((tg / "schema_catalog.json").read_text(encoding="utf-8"))
    check("2e. schema_catalog.json covers all 24 vertices", len(catalog.get("vertices", {})) == 24)


# 3 — product model
def check_products() -> None:
    from app.revenue.products import class_for_group, product_group_rows, resolve_product

    cases = {
        ("ELIS", "EQ"): "twhs_equities", ("ELIS", "OP"): "twhs_options",
        ("LEND", "SBL"): "lending_sbl", ("LEND", "MGN"): "lending_margin",
        ("OISC", ""): "managed_accounts", ("UMA", ""): "managed_uma",
        ("ZZZZ", ""): "unmapped",
    }
    bad = {c: resolve_product(*c) for c in cases if resolve_product(*c) != cases[c]}
    check("3a. resolve_product per spec (sub-code splits + unmapped)", not bad,
          str(bad) if bad else "7 cases")
    rows = product_group_rows()
    check("3b. 24 display groups + unmapped seeded", len(rows) == 25, f"{len(rows)} rows")
    check("3c. UMA displays as its own row AND classes Recurring (parallel dimensions)",
          resolve_product("UMA") == "managed_uma" and class_for_group("managed_uma") == "RECURRING")


# 4 — CSVs match manifest
def check_manifest_counts() -> None:
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    mism = []
    for entry in manifest["files"]:
        actual = len(read_csv(ROOT / "data" / entry["file"]))
        if actual != entry["expected_rows"]:
            mism.append(f"{entry['file']}: manifest {entry['expected_rows']} vs csv {actual}")
    check("4. every CSV row count matches manifest.json", not mism,
          "; ".join(mism) or f"{len(manifest['files'])} files")


# 5 — graph load counts
def check_graph_load() -> None:
    from app.graph.client import get_graph_client
    from app.ingestion.manifest_check import verify_counts_against_manifest

    try:
        report = verify_counts_against_manifest(get_graph_client())
        check("5. graph counts match manifest (fail-loud check ran)", report["ok"],
              f"{len(report['checked'])} targets, {len(report['mismatches'])} mismatches")
    except RuntimeError as exc:
        check("5. graph counts match manifest (fail-loud check ran)", False, str(exc)[:200])


# 6 — independent monthly recomputation
def check_monthly_totals() -> None:
    txns = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_revenue_transaction.csv")
    monthly = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_monthly_revenue.csv")

    # independent recomputation, straight off the CSV, credited-revenue rule applied here
    expect = defaultdict(float)
    for t in txns:
        credited = t["reason_cd"] == "__NONE__"
        amt = float(t["credited_amt"]) if credited else 0.0
        expect[(t["advisor_sid"], t["month_id"], t["product_id"])] += amt
    got = {(m["advisor_sid"], m["month_id"], m["product_id"]): float(m["credited_amt"]) for m in monthly}
    mism = [k for k in set(expect) | set(got) if abs(expect.get(k, 0.0) - got.get(k, 0.0)) > 0.011]
    check("6a. monthly credited totals match independent recomputation", not mism,
          f"{len(mism)} mismatching (advisor,month,product) keys" if mism else f"{len(got)} aggregate rows")

    bad_rows = [t for t in txns if t["reason_cd"] != "__NONE__" and float(t["credited_amt"]) != 0.0]
    check("6b. reason-coded rows carry zero credited_amt (loaded as non_credited)", not bad_rows,
          f"{len(bad_rows)} violations" if bad_rows else "credited rule holds")

    mr_ids = [m["mr_id"] for m in monthly]
    ok_ids = all(m["mr_id"] == f"{m['advisor_sid']}|{m['month_id']}|{m['product_id']}" for m in monthly)
    check("6c. mr_id = advisor_sid|month_id|product_id (advisor-scoped key)",
          ok_ids and len(set(mr_ids)) == len(mr_ids))


# 7 — scenario coverage
def check_scenarios() -> None:
    txns = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_revenue_transaction.csv")
    reduced = {t["acct_key"] for t in txns if float(t["eff_disc_pct"] or 0) > 10}
    recorded = {t["acct_key"] for t in txns if float(t["grid_reduction"] or 0) > 0}
    check("7a. fee reductions >10% with recorded AND unrecorded grid_reduction",
          len(reduced) >= 11 and 0 < len(recorded) < len(reduced),
          f"{len(reduced)} above threshold, {len(recorded)} recorded")
    transfers = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_account_transfer.csv")
    check("7b. inbound and outbound transfers", any(t["to_advisor_sid"].startswith("V") for t in transfers)
          and any(t["from_advisor_sid"].startswith("V") for t in transfers), f"{len(transfers)} transfers")
    accts = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_account.csv")
    check("7c. accounts opened in scope (Q2)", any(a["opened_in_scope"] == "true" for a in accts))
    am = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_account_month.csv")
    check("7d. accounts zeroed between months",
          any(r["is_zero_balance"] == "true" and r["month_id"] == "202605" for r in am))
    teams = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_team_agreement.csv")
    check("7e. team agreements with fractional shares", len(teams) > 0
          and all(0.0 < float(t["prm_share_pct"]) <= 1.0 for t in teams), f"{len(teams)} agreements")
    monthly = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_monthly_revenue.csv")
    check("7f. unmapped product visible, never dropped",
          any(m["group_id"] == "unmapped" for m in monthly))
    flows = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_advisor_flow_month.csv")
    months = {f["month_id"] for f in flows}
    nnm = defaultdict(float)
    for f in flows:
        nnm[f["advisor_sid"]] += float(f["total_net_flows"])
    check("7g. flows Apr+May only, one advisor above $4MM NNM",
          months == {"202604", "202605"} and max(nnm.values()) >= 4_000_000,
          f"max NNM ${max(nnm.values()):,.0f}")
    advisors = read_csv(ROOT / "data" / "vertices" / "phx_dm_pce_advisor.csv")
    check("7h. blank advisor name stays blank; non-cohort counterparties loaded",
          any(not a["advisor_name"] for a in advisors) and any(a["in_cohort"] == "false" for a in advisors))


# 8 — /api/health
def check_health() -> None:
    from fastapi.testclient import TestClient

    from app.api.main import app

    with TestClient(app) as client:
        r = client.get("/api/health")
    ok = r.status_code == 200
    body = r.json() if ok else {}
    check("8a. GET /api/health returns 200 and healthy=true",
          ok and body.get("healthy") is True, f"status {r.status_code}")
    check("8b. health reports graph tier + per-vertex counts",
          body.get("graph", {}).get("tier") is not None and len(body.get("vertex_counts", {})) == 16,
          f"tier={body.get('graph', {}).get('tier')}, {len(body.get('vertex_counts', {}))} vertex types")
    llm = body.get("llm", {})
    check("8c. health reports LLM reachability honestly",
          "reachable" in llm and ("error" in llm or llm["reachable"]),
          f"mode={llm.get('mode')} reachable={llm.get('reachable')}")


def main() -> None:
    for fn in (check_imports, check_ddl, check_products, check_manifest_counts,
               check_graph_load, check_monthly_totals, check_scenarios, check_health):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — a crashed check is a FAIL, not a crash
            check(f"{fn.__name__} (crashed)", False, f"{type(exc).__name__}: {exc}")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

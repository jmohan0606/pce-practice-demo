#!/usr/bin/env python3
"""Round 2a task 4 — reconcile the load: prove the counts three ways.

    python3 scripts/reconcile_load.py [--raw data/real/_raw] [--data-dir data/real]
                                      [--expected docs/data/extraction/EXPECTED_COUNTS.json]
                                      [--no-baseline]

The operator's requirement: "accurately making sure all the intended records
and its counts are matching." Three INDEPENDENT numbers per entity:

  source     the row count PostgreSQL returned at extraction time, from
             extract_checkpoint.json (written per chunk as it completed)
  extracted  the rows actually in the raw CSVs, recounted NOW from the files
             (a truncated file from a full disk fails HERE, not downstream)
  loaded     SELECT count(*) from the graph, compared against the BUILT rows

Between extracted and loaded sits the build, whose build_report.json records
every explained delta (out-of-scope rows, dedupes, superseded snapshots, the
CRM in-scope filter) — so raw − explained == built == loaded is provable per
entity, and an UNEXPLAINED difference is a hard failure naming the entity and
the two numbers that differ. A load that silently dropped 40,000 rows is worse
than one that failed.

The two flat-file sources reconcile the same way: the CRM export's raw count
vs in-scope kept (out-of-scope REPORTED by the build, *_CWM_INVALID kept), and
the four NNM files' parsed rows vs the advisor_nnm vertex.

The committed baseline (docs/data/extraction/EXPECTED_COUNTS.json — MEASURED
client counts) is compared wherever it carries a number, so a rerun checks
against known truth, not just internal consistency. --no-baseline skips that
comparison for fixture/test drops whose sizes legitimately differ.

Exit 0 = every entity matches on all applicable counts. Exit 1 = mismatch.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []

# raw family -> (delta key in build_report.transform_deltas, graph target)
RAW_TO_ENTITY = {
    "raw_revenue_transaction.csv": ("revenue_transaction", "phx_dm_pce_revenue_transaction"),
    "raw_account.csv": ("account", "phx_dm_pce_account"),
    "raw_acct_eci_rel.csv": ("account_eci_rel", "phx_dm_pce_account_eci_rel"),
    "raw_acct_eci_map.csv": ("account_eci_map", "phx_dm_pce_account_eci_map"),
    "raw_rr_changes.csv": ("account_transfer", "phx_dm_pce_account_transfer"),
    "raw_adv_flows.csv": ("advisor_flow_month", "phx_dm_pce_advisor_flow_month"),
    "raw_advisor.csv": ("advisor", "phx_dm_pce_advisor"),
    "raw_team_agreement.csv": ("team_agreement", "phx_dm_pce_team_agreement"),
    "raw_month_meta.csv": ("month", "phx_dm_pce_month"),
}
# checkpoint chunk-id prefixes per family (single-table ids equal the stem)
FAMILY_CHUNK_PREFIX = {
    "raw_revenue_transaction.csv": "raw_txn_",
    "raw_monthly_balance.csv": "raw_balance_",
    "raw_account.csv": "raw_account",
    "raw_acct_eci_rel.csv": "raw_acct_eci_rel",
    "raw_acct_eci_map.csv": "raw_acct_eci_map",
}


def fail(msg: str) -> None:
    FAILURES.append(msg)


def count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else ("—" if n is None else str(n))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default="data/real/_raw")
    ap.add_argument("--data-dir", default="data/real")
    ap.add_argument("--expected", default="docs/data/extraction/EXPECTED_COUNTS.json")
    ap.add_argument("--no-baseline", action="store_true",
                    help="skip the committed-baseline comparison (fixture/test "
                         "drops whose sizes legitimately differ)")
    args = ap.parse_args()
    raw_dir = Path(args.raw)
    data_dir = Path(args.data_dir)

    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault(
        "SQLITE_DB_PATH", str(data_dir / "checkpoints" / "ingestion.db"))
    from app.graph.client import get_graph_client  # noqa: E402 — after env
    from app.ingestion.graph_validation import _parse_count  # noqa: E402
    from scripts.build_real_data import (  # noqa: E402
        CHUNK_FAMILIES, detect_sources, family_files,
    )
    from scripts import parse_nnm  # noqa: E402

    manifest_path = data_dir / "manifest.json"
    report_path = data_dir / "build_report.json"
    for p in (manifest_path, report_path):
        if not p.exists():
            print(f"ERROR: {p} not found — run scripts/build_real_data.py first",
                  file=sys.stderr)
            return 1
    manifest = json.loads(manifest_path.read_text())
    build_report = json.loads(report_path.read_text())
    deltas = build_report.get("transform_deltas", {})
    baseline = {}
    if not args.no_baseline:
        bp = Path(args.expected)
        if bp.exists():
            baseline = json.loads(bp.read_text()).get("raw", {})
        else:
            print(f"WARNING: baseline {bp} not found — internal consistency only")

    sources = detect_sources(raw_dir)
    graph = get_graph_client()

    # ---- source (checkpoint) vs extracted (raw CSVs, recounted now) --------
    cp_path = raw_dir / "extract_checkpoint.json"
    cp_rows: dict[str, int] = {}
    if cp_path.exists():
        cp = json.loads(cp_path.read_text())
        for chunk_id, rec in cp.get("completed", {}).items():
            cp_rows[chunk_id] = rec.get("rows", 0)
    else:
        print("(no extract_checkpoint.json — source column unavailable; "
              "extracted vs loaded still fully checked)")

    def family_source(family: str) -> int | None:
        if not cp_rows:
            return None
        prefix = FAMILY_CHUNK_PREFIX.get(family, family[:-4])
        ids = [c for c in cp_rows
               if c == family[:-4] or c.startswith(prefix)]
        return sum(cp_rows[c] for c in ids) if ids else None

    def family_extracted(family: str) -> int:
        return sum(count_csv_rows(p) for p in family_files(raw_dir, sources, family))

    def graph_count(target: str, kind: str) -> int | None:
        try:
            return _parse_count(graph.statistics(kind=kind, target_type=target), target)
        except Exception as exc:  # noqa: BLE001 — an unreadable count is a failure
            fail(f"{target}: graph count unreadable ({type(exc).__name__}: {exc})")
            return None

    built = {f["target"]: f["expected_rows"] for f in manifest["files"]}
    kind_of = {f["target"]: f["kind"] for f in manifest["files"]}
    file_of = {f["target"]: f["file"] for f in manifest["files"]}

    print(f"{'entity':38} {'source':>12} {'extracted':>12} {'built':>12} "
          f"{'loaded':>12}  match")
    print("-" * 96)

    def row(label, source, extracted, built_n, loaded, ok, note=""):
        mark = "✓" if ok else "✗"
        print(f"{label:38} {fmt(source):>12} {fmt(extracted):>12} "
              f"{fmt(built_n):>12} {fmt(loaded):>12}  {mark}{'  ' + note if note else ''}")

    # ---- raw-mapped entities: the full three-way proof ----------------------
    for family, (dkey, target) in RAW_TO_ENTITY.items():
        source = family_source(family)
        extracted = family_extracted(family)
        d = deltas.get(dkey, {})
        built_n = built.get(target)
        loaded = graph_count(target, kind_of[target])
        notes = []
        ok = True
        if source is not None and source != extracted:
            ok = False
            fail(f"{family}: checkpoint recorded {source} rows but the raw "
                 f"CSVs hold {extracted} — truncated or altered extract")
        explained = sum(v for k, v in d.items()
                        if k not in ("raw_rows", "rows") and isinstance(v, int))
        if d:
            if d.get("raw_rows") != extracted:
                ok = False
                fail(f"{family}: build read {d.get('raw_rows')} raw rows but the "
                     f"files now hold {extracted} — the drop changed after the build")
            if extracted - explained != d.get("rows"):
                ok = False
                fail(f"{family}: {extracted} raw − {explained} explained "
                     f"(={extracted - explained}) != {d.get('rows')} built")
            if explained:
                notes.append(f"−{explained} explained "
                             f"({', '.join(f'{k} {v}' for k, v in d.items() if k not in ('raw_rows', 'rows') and isinstance(v, int) and v)})")
        if built_n is not None and d and d.get("rows") != built_n:
            ok = False
            fail(f"{target}: build_report rows {d.get('rows')} != manifest "
                 f"expected_rows {built_n}")
        if loaded is not None and built_n is not None and loaded != built_n:
            ok = False
            fail(f"{target}: built {built_n} rows but the graph holds {loaded}")
        base = baseline.get(family[:-4], {}).get("rows") if baseline else None
        if base is not None and base != extracted:
            ok = False
            fail(f"{family}: extracted {extracted} != committed baseline {base} "
                 f"(EXPECTED_COUNTS.json)")
        row(dkey, source, extracted, built_n, loaded, ok, "; ".join(notes))

    # ---- balances feed account_month (not 1:1) — source vs extracted only ---
    bal_source = family_source("raw_monthly_balance.csv")
    bal_extracted = family_extracted("raw_monthly_balance.csv")
    bal_ok = bal_source is None or bal_source == bal_extracted
    if not bal_ok:
        fail(f"raw_monthly_balance: checkpoint recorded {bal_source} rows but "
             f"the raw CSVs hold {bal_extracted}")
    base = baseline.get("raw_monthly_balance", {}).get("rows") if baseline else None
    if base is not None and base != bal_extracted:
        bal_ok = False
        fail(f"raw_monthly_balance: extracted {bal_extracted} != committed "
             f"baseline {base}")
    row("monthly_balance (feeds account_month)", bal_source, bal_extracted,
        None, None, bal_ok, "grain differs: per-account-month balance rows")

    # ---- the two flat-file sources (operator requirement, Round 2a) ---------
    crm_file = raw_dir / sources["crm_file"]
    crm_extracted = count_csv_rows(crm_file)
    d = deltas.get("opportunity", {})
    opp_built = built.get("phx_dm_pce_opportunity")
    opp_loaded = graph_count("phx_dm_pce_opportunity", "vertex")
    crm_ok = True
    if d:
        if d.get("raw_rows") != crm_extracted:
            crm_ok = False
            fail(f"{sources['crm_file']}: build read {d.get('raw_rows')} rows "
                 f"but the file now holds {crm_extracted}")
        if crm_extracted - d.get("out_of_scope_dropped", 0) != d.get("rows"):
            crm_ok = False
            fail(f"CRM: {crm_extracted} raw − {d.get('out_of_scope_dropped')} "
                 f"out-of-scope != {d.get('rows')} kept")
        if d.get("rows") != opp_built:
            crm_ok = False
            fail(f"opportunity: build kept {d.get('rows')} but manifest says {opp_built}")
    if opp_loaded is not None and opp_built is not None and opp_loaded != opp_built:
        crm_ok = False
        fail(f"phx_dm_pce_opportunity: built {opp_built} but graph holds {opp_loaded}")
    base = baseline.get("crm_opportunities", {}).get("rows") if baseline else None
    if base is not None and base != crm_extracted:
        crm_ok = False
        fail(f"CRM export: {crm_extracted} rows != committed baseline {base}")
    row("opportunity (CRM flat file)", None, crm_extracted, opp_built,
        opp_loaded, crm_ok,
        f"−{d.get('out_of_scope_dropped', 0)} out-of-scope (reported); "
        f"{d.get('invalid_advisor_kept', 0)} *_CWM_INVALID kept" if d else "")

    nnm_extracted = len(parse_nnm.parse_nnm_dir(raw_dir))
    nnm_built = built.get("phx_dm_pce_advisor_nnm")
    nnm_loaded = graph_count("phx_dm_pce_advisor_nnm", "vertex")
    nnm_ok = nnm_extracted == nnm_built and (nnm_loaded is None or nnm_loaded == nnm_built)
    if nnm_extracted != nnm_built:
        fail(f"advisor_nnm: the four NNM files parse to {nnm_extracted} rows "
             f"but the built vertex file holds {nnm_built}")
    if nnm_loaded is not None and nnm_loaded != nnm_built:
        fail(f"phx_dm_pce_advisor_nnm: built {nnm_built} but graph holds {nnm_loaded}")
    row("advisor_nnm (four NNM flat files)", None, nnm_extracted, nnm_built,
        nnm_loaded, nnm_ok)

    # ---- every remaining entity (derived vertices + all edges): built==loaded
    covered = {t for _, t in RAW_TO_ENTITY.values()} | {
        "phx_dm_pce_opportunity", "phx_dm_pce_advisor_nnm"}
    for f in manifest["files"]:
        target = f["target"]
        if target in covered:
            continue
        built_n = f["expected_rows"]
        actual_file = count_csv_rows(data_dir / file_of[target])
        loaded = graph_count(target, f["kind"])
        ok = actual_file == built_n and (loaded is None or loaded == built_n)
        if actual_file != built_n:
            fail(f"{target}: manifest says {built_n} rows but the built CSV "
                 f"holds {actual_file}")
        if loaded is not None and loaded != built_n:
            fail(f"{target}: built {built_n} rows but the graph holds {loaded}")
        row(target.replace("phx_dm_pce_", "") + (" (edge)" if f["kind"] == "edge" else " (derived)"),
            None, None, built_n, loaded, ok)

    print("-" * 96)
    if FAILURES:
        print(f"\nRECONCILIATION FAILED — {len(FAILURES)} mismatch(es):")
        for m in FAILURES:
            print(f"  ✗ {m}")
        print("\nA load that silently dropped rows is worse than one that "
              "failed — every downstream figure would be quietly wrong. Fix "
              "and re-run before the Phase 4 review gate.")
        return 1
    print(f"\nRECONCILIATION PASSED — every entity matches on all applicable "
          f"counts ({len(manifest['files'])} targets"
          + ("" if args.no_baseline else " + committed baseline") + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())

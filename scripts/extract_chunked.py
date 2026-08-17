"""Round 1 task 5 / Round 2a task 2 — chunked, resumable PostgreSQL extraction.

    python3 scripts/extract_chunked.py --months 202604,202605,202606 \\
        --advisors-file data/real/cohort.txt [--batch-size 200] [--buckets 4] \\
        [--out data/real/_raw] [--dry-run] [--restart] [--skip-disk-check]

Two hard constraints in the client environment make one-query-for-everything
impossible: a 900-second statement timeout and a 30-minute IAM token. So the
plan chunks EVERYTHING that is large at firm scale (5,746 advisors / 12.4M
transactions — Round 2a):

- Transactions: MONTH x ADVISOR BATCH chunks (default 200 advisors) —
  ``raw_txn_202604_b001.csv``. 87 chunks at firm scale, ~143k rows each.
- Monthly balances: ONE CHUNK PER MONTH (``raw_balance_202604.csv`` …) —
  never a UNION; 8.68M rows in one query will not finish in 900s.
- raw_account / raw_acct_eci_rel / raw_acct_eci_map: ``--buckets`` (default 4)
  deterministic account-key-hash chunks each (``raw_account_b001.csv`` …) via
  ``mod(abs(hashtext(s.k)), :n) = :b`` over the scoped_acct temp table —
  reproducible and resumable; raise --buckets in a slow environment.
- Everything else is genuinely small and stays a single chunk.

EVERY chunk is a checkpoint entry: ``extract_checkpoint.json`` records rows/
seconds/path per completed chunk, and on ANY error — token expiry included —
the script saves the checkpoint and exits cleanly with the exact resume
instruction. Rerunning resumes at the first uncompleted chunk, NEVER from the
start (a token expiry mid-acct_eci_rel resumes at the next bucket).

SESSION SETUP: each connection first creates the cohort_adv and scoped_acct
TEMP tables (generate_extraction_sql.session_setup_statements) — computed once
per session, joined by every scoped query instead of re-scanning the 12.4M-row
trade table per table. A temp table dies with its session; a token refresh is
a reconnect, so the setup re-runs automatically on every (re)connection.

DISK: refuses to start with under 20 GB free on the output filesystem (15 GB
measured peak + headroom) — a truncated CSV from a full disk can pass a naive
row-count check, the worst kind of failure. --skip-disk-check for an operator
who knows better.

Extraction and ingestion are DECOUPLED: extract everything to CSV, run
scripts/validate_raw_extracts.py, get the operator's review (runbook Phase 4),
and only then load. The CRM export (crm_opportunities.csv) and the four NNM
.txt files are FLAT FILES, not PostgreSQL — place them in the same output
directory by hand (see CLIENT_ENV_RUNBOOK.md).

SQL comes from scripts/generate_extraction_sql.templates() — one source of
truth for every SELECT list. Connection: set PCE_PG_DSN (or standard PG* env
vars) for psycopg2/psycopg.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_extraction_sql import (  # noqa: E402
    BALANCE_TABLES,
    BUCKET_MARKER,
    BUCKETED_SQL,
    bucket_predicate,
    session_setup_statements,
    templates,
)

CHECKPOINT_NAME = "extract_checkpoint.json"
EXPECTED_COUNTS_PATH = ROOT / "docs/data/extraction/EXPECTED_COUNTS.json"
MIN_FREE_GB = 20
# ~2M rows is the per-chunk ceiling a 900s statement timeout tolerates with
# margin; a chunk projecting above it needs a smaller batch / more buckets.
CHUNK_ROW_WARN = 2_000_000

# Genuinely small single-chunk tables (Round 2a: the four multi-million-row
# extracts moved OUT of this list into month/bucket chunks). Advisors first so
# a partial run still yields a coherent review set. raw_crm_opportunity.sql is
# EXCLUDED on purpose: the CRM export is a flat file, not a PostgreSQL extract.
SINGLE_TABLES = [
    "raw_advisor_flags.sql", "raw_advisor.sql", "raw_product_hierarchy.sql",
    "raw_rr_changes.sql", "raw_month_meta.sql", "raw_team_agreement.sql",
    "raw_adv_flows.sql",
]


def month_bounds(month_id: str) -> tuple[str, str]:
    y, m = int(month_id[:4]), int(month_id[4:6])
    nxt = (y + (m == 12), 1 if m == 12 else m + 1)
    return f"{y:04d}-{m:02d}-01", f"{nxt[0]:04d}-{nxt[1]:02d}-01"


def txn_chunk_sql(sids: list[str], month_id: str) -> str:
    """The transaction template re-scoped to one month x one advisor batch.
    The template carries exactly two DATE literals (the full range) and one
    cohort_adv join line; the dates are replaced with the chunk month's bounds
    and the join with an inline batch (<= --batch-size SIDs — the full cohort
    is NEVER inlined). Both shapes are asserted so a template edit fails
    loudly here instead of extracting wrong."""
    sql = templates()["raw_revenue_transaction.sql"]
    dates = re.findall(r"DATE '(\d{4}-\d{2}-\d{2})'", sql)
    if len(dates) != 2:
        raise RuntimeError(
            f"raw_revenue_transaction.sql template no longer carries exactly "
            f"two DATE literals (found {len(dates)}) — update txn_chunk_sql "
            f"before extracting")
    join_line = "JOIN   cohort_adv ca ON ca.advisor_sid = d.advisor_sid\n"
    if join_line not in sql:
        raise RuntimeError(
            "raw_revenue_transaction.sql template no longer carries the "
            "cohort_adv join line — update txn_chunk_sql before extracting")
    start, end = month_bounds(month_id)
    sql = sql.replace(f"DATE '{dates[0]}'", f"DATE '{start}'", 1)
    sql = sql.replace(f"DATE '{dates[1]}'", f"DATE '{end}'", 1)
    in_list = ",".join(f"'{s}'" for s in sids)
    sql = sql.replace(join_line, "", 1)
    sql = sql.rstrip().rstrip(";") + f"\n  AND  d.advisor_sid IN ({in_list});"
    return sql


def bucket_chunk_sql(sql_name: str, n_buckets: int, bucket: int) -> str:
    sql = templates()[sql_name]
    if BUCKET_MARKER not in sql:
        raise RuntimeError(
            f"{sql_name} template no longer carries the {BUCKET_MARKER} marker "
            f"— update the template or the bucket plan before extracting")
    return sql.replace(BUCKET_MARKER, bucket_predicate(n_buckets, bucket))


def build_plan(months: list[str], advisors: list[str], batch_size: int,
               buckets: int) -> list[dict]:
    """The full chunk plan. chunk_id is stable — the checkpoint keys on it.
    Order: small singles, per-month balances, account-key buckets, then the
    month x advisor-batch transaction chunks."""
    plan = [{"chunk_id": name[:-4], "kind": "table", "sql_name": name,
             "out_name": name[:-4] + ".csv"} for name in SINGLE_TABLES]
    for month in months:
        if month not in BALANCE_TABLES:
            raise SystemExit(
                f"ERROR: no monthly balance table known for {month} — extend "
                f"BALANCE_TABLES in scripts/generate_extraction_sql.py")
        plan.append({"chunk_id": f"raw_balance_{month}", "kind": "balance",
                     "month": month, "out_name": f"raw_balance_{month}.csv"})
    for sql_name in BUCKETED_SQL:
        stem = sql_name[:-4]
        for b in range(buckets):
            plan.append({"chunk_id": f"{stem}_b{b + 1:03d}", "kind": "bucket",
                         "sql_name": sql_name, "bucket": b, "n_buckets": buckets,
                         "out_name": f"{stem}_b{b + 1:03d}.csv"})
    batches = [advisors[i:i + batch_size] for i in range(0, len(advisors), batch_size)]
    for month in months:
        for b, sids in enumerate(batches, start=1):
            plan.append({"chunk_id": f"raw_txn_{month}_b{b:03d}", "kind": "txn",
                         "month": month, "batch_no": b, "sids": sids,
                         "out_name": f"raw_txn_{month}_b{b:03d}.csv"})
    return plan


def chunk_estimate(chunk: dict, baseline: dict | None, n_txn_batches: int) -> int | None:
    """Projected rows per chunk from the committed EXPECTED_COUNTS baseline
    (measured client counts) — labelled a projection, never a promise."""
    if not baseline:
        return None
    raw = baseline.get("raw", {})
    if chunk["kind"] == "txn":
        per_month = (raw.get("raw_revenue_transaction") or {}).get("per_month") or {}
        total = per_month.get(chunk["month"])
        return round(total / max(n_txn_batches, 1)) if total else None
    if chunk["kind"] == "balance":
        per_month = (raw.get("raw_monthly_balance") or {}).get("per_month") or {}
        return per_month.get(chunk["month"])
    if chunk["kind"] == "bucket":
        total = (raw.get(chunk["sql_name"][:-4]) or {}).get("rows")
        return round(total / chunk["n_buckets"]) if total else None
    return (raw.get(chunk["sql_name"][:-4]) or {}).get("rows")


def plan_fingerprint(months: list[str], advisors: list[str], batch_size: int,
                     buckets: int) -> str:
    basis = json.dumps({"months": months, "advisors": advisors,
                        "batch_size": batch_size, "buckets": buckets},
                       sort_keys=True)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def load_checkpoint(out_dir: Path) -> dict:
    path = out_dir / CHECKPOINT_NAME
    if path.exists():
        return json.loads(path.read_text())
    return {"fingerprint": None, "completed": {}}


def save_checkpoint(out_dir: Path, cp: dict) -> None:
    (out_dir / CHECKPOINT_NAME).write_text(json.dumps(cp, indent=2))


def check_free_disk(out_dir: Path, skip: bool) -> bool:
    free_gb = shutil.disk_usage(out_dir).free / 1e9
    if free_gb >= MIN_FREE_GB:
        return True
    if skip:
        print(f"WARNING: only {free_gb:.1f} GB free on {out_dir} "
              f"(< {MIN_FREE_GB} GB) — proceeding on --skip-disk-check")
        return True
    print(f"ERROR: {free_gb:.1f} GB free on {out_dir}'s filesystem — the full "
          f"extract+build peaks at ~15 GB and needs {MIN_FREE_GB} GB headroom. "
          f"A full disk mid-extract produces truncated CSVs that can pass a "
          f"naive row count. Free space or pass --skip-disk-check.",
          file=sys.stderr)
    return False


def default_connect():
    """psycopg2 (or psycopg 3) via PCE_PG_DSN / standard PG* env vars."""
    dsn = os.environ.get("PCE_PG_DSN", "")
    try:
        import psycopg2  # type: ignore

        return psycopg2.connect(dsn) if dsn else psycopg2.connect()
    except ImportError:
        try:
            import psycopg  # type: ignore

            return psycopg.connect(dsn) if dsn else psycopg.connect()
        except ImportError as exc:
            raise RuntimeError(
                "no PostgreSQL driver installed — pip install psycopg2-binary "
                "(or psycopg) from the client artifactory") from exc


def setup_session(conn, advisors: list[str], statement_timeout: str) -> None:
    """Create the per-session temp tables (cohort_adv + scoped_acct). Runs on
    EVERY connection — a temp table does not survive a reconnect, and a token
    refresh is a reconnect (spec 2.2 states this explicitly)."""
    cur = conn.cursor()
    cur.execute(f"SET statement_timeout = '{statement_timeout}'")
    for stmt in session_setup_statements(advisors):
        cur.execute(stmt)
    cur.close()


def chunk_sql(chunk: dict, advisors: list[str]) -> str:
    if chunk["kind"] == "txn":
        return txn_chunk_sql(chunk["sids"], chunk["month"])
    if chunk["kind"] == "balance":
        from scripts.generate_extraction_sql import monthly_balance_sql

        return monthly_balance_sql(chunk["month"])
    if chunk["kind"] == "bucket":
        return bucket_chunk_sql(chunk["sql_name"], chunk["n_buckets"], chunk["bucket"])
    return templates(advisors)[chunk["sql_name"]]


def run_chunk(conn, chunk: dict, advisors: list[str], out_dir: Path,
              statement_timeout: str) -> int:
    sql = chunk_sql(chunk, advisors)
    cur = conn.cursor()
    cur.execute(f"SET statement_timeout = '{statement_timeout}'")
    cur.execute(sql)
    columns = [d[0] for d in cur.description]
    out_path = out_dir / chunk["out_name"]
    tmp_path = out_path.with_suffix(".csv.part")
    n = 0
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        while True:
            rows = cur.fetchmany(10_000)
            if not rows:
                break
            writer.writerows(rows)
            n += len(rows)
    tmp_path.replace(out_path)  # a chunk file is either complete or absent
    cur.close()
    return n


def main(argv: list[str] | None = None, connect=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", required=True,
                    help="comma-separated month ids, e.g. 202604,202605,202606 "
                         "(explicit — never guessed)")
    ap.add_argument("--advisors-file", required=True,
                    help="one advisor_sid per line (the full book — Round 2a: "
                         "the cohort is the firm, 5,746 advisors)")
    ap.add_argument("--batch-size", type=int, default=200,
                    help="advisors per transaction chunk (default 200 — 87 "
                         "chunks of ~143k rows at firm scale)")
    ap.add_argument("--buckets", type=int, default=4,
                    help="account-key hash buckets for raw_account / "
                         "raw_acct_eci_rel / raw_acct_eci_map (default 4; "
                         "raise it if a chunk projects above ~2M rows)")
    ap.add_argument("--out", default="data/real/_raw", help="output directory")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the full chunk plan with per-chunk row "
                         "projections; extract nothing")
    ap.add_argument("--restart", action="store_true",
                    help="EXPLICIT full restart: clear the checkpoint first "
                         "(resume is the default)")
    ap.add_argument("--skip-disk-check", action="store_true",
                    help="proceed even with under 20 GB free (operator "
                         "override; truncated-CSV risk is yours)")
    ap.add_argument("--statement-timeout", default="600s",
                    help="per-query statement_timeout (default 600s — inside "
                         "the client's 900s hard limit)")
    args = ap.parse_args(argv)

    months = [m.strip() for m in args.months.split(",") if m.strip()]
    bad = [m for m in months if not re.fullmatch(r"\d{6}", m)]
    if bad:
        print(f"ERROR: month ids must be YYYYMM — got {bad}", file=sys.stderr)
        return 1
    if args.buckets < 1:
        print("ERROR: --buckets must be >= 1", file=sys.stderr)
        return 1
    adv_path = Path(args.advisors_file)
    if not adv_path.exists():
        print(f"ERROR: advisors file {adv_path} not found", file=sys.stderr)
        return 1
    advisors = [line.strip() for line in adv_path.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
    if not advisors:
        print(f"ERROR: advisors file {adv_path} is empty", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = build_plan(months, advisors, args.batch_size, args.buckets)
    fingerprint = plan_fingerprint(months, advisors, args.batch_size, args.buckets)
    n_txn = sum(1 for c in plan if c["kind"] == "txn")
    n_txn_batches = (len(advisors) + args.batch_size - 1) // args.batch_size
    n_bucket = sum(1 for c in plan if c["kind"] == "bucket")
    print(f"chunk plan: {len(SINGLE_TABLES)} single-table chunks + "
          f"{len(months)} monthly-balance chunks + {n_bucket} account-bucket "
          f"chunks ({len(BUCKETED_SQL)} tables x {args.buckets} buckets) + "
          f"{n_txn} transaction chunks ({len(months)} months x "
          f"{n_txn_batches} advisor batches of <= {args.batch_size}) "
          f"= {len(plan)} chunks -> {out_dir}")

    baseline = None
    if EXPECTED_COUNTS_PATH.exists():
        baseline = json.loads(EXPECTED_COUNTS_PATH.read_text())

    if args.dry_run:
        oversize = []
        for c in plan:
            est = chunk_estimate(c, baseline, n_txn_batches)
            est_s = f"~{est:,} rows (projected)" if est is not None else "rows unknown"
            label = (f"{c['chunk_id']}  (month {c['month']}, batch {c['batch_no']}: "
                     f"{len(c['sids'])} advisors)" if c["kind"] == "txn"
                     else c["chunk_id"])
            print(f"  {label}  -> {c['out_name']}  [{est_s}]")
            # balance chunks are exempt: spec 2.4's own design is one chunk
            # per month (~2.9M each) — month IS the finest split for those
            # tables, and --buckets does not apply to them.
            if est is not None and est > CHUNK_ROW_WARN and c["kind"] != "balance":
                oversize.append((c["chunk_id"], est))
        if oversize:
            print(f"  WARNING: {len(oversize)} chunk(s) project above "
                  f"{CHUNK_ROW_WARN:,} rows: "
                  + ", ".join(f"{cid} (~{e:,})" for cid, e in oversize)
                  + " — raise --buckets / lower --batch-size before extracting")
        estimate_err = None
        try:
            conn = (connect or default_connect)()
            cur = conn.cursor()
            for month in months:
                start, end = month_bounds(month)
                cur.execute(
                    "SELECT count(*) FROM pcr.fpic_daily_trade_details_tb_prod "
                    "WHERE trade_dt >= DATE %s AND trade_dt < DATE %s",
                    (start, end))
                print(f"  live transaction row count {month}: {cur.fetchone()[0]:,}")
            conn.close()
        except Exception as exc:  # noqa: BLE001 — live estimates are optional in dry-run
            estimate_err = f"{type(exc).__name__}: {exc}"
        if estimate_err:
            print(f"  live row counts unavailable (no connection): {estimate_err}")
        print("dry run — nothing extracted.")
        return 0

    if not check_free_disk(out_dir, args.skip_disk_check):
        return 1

    cp = load_checkpoint(out_dir)
    if args.restart:
        print("--restart: clearing checkpoint (full re-extract)")
        cp = {"fingerprint": fingerprint, "completed": {}}
        save_checkpoint(out_dir, cp)
    elif cp["fingerprint"] and cp["fingerprint"] != fingerprint:
        print(f"ERROR: checkpoint in {out_dir} was written for a DIFFERENT plan "
              f"(months/advisors/batch/buckets changed). Rerun with the "
              f"original arguments to resume it, or pass --restart to discard "
              f"it.", file=sys.stderr)
        return 1
    cp["fingerprint"] = fingerprint

    done = [c for c in plan if c["chunk_id"] in cp["completed"]]
    todo = [c for c in plan if c["chunk_id"] not in cp["completed"]]
    if done:
        print(f"resume: {len(done)} chunk(s) already complete — skipped; "
              f"{len(todo)} to go")
    if not todo:
        print("nothing to do — every chunk is complete. "
              "Next: python3 scripts/validate_raw_extracts.py")
        return 0

    try:
        conn = (connect or default_connect)()
        # per-session temp tables — re-created on EVERY connection (a token
        # refresh is a reconnect; the temp tables died with the old session)
        setup_session(conn, advisors, args.statement_timeout)
        print("session setup: cohort_adv + scoped_acct temp tables created "
              "(re-created automatically on every reconnect)")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not connect to PostgreSQL / create the session "
              f"temp tables: {exc}\n"
              f"Set PCE_PG_DSN (or PG* env vars), refresh the IAM token if "
              f"expired, then rerun the same command — completed chunks are "
              f"checkpointed and will be skipped.", file=sys.stderr)
        return 2

    for chunk in todo:
        t0 = time.time()
        try:
            n = run_chunk(conn, chunk, advisors, out_dir, args.statement_timeout)
        except KeyboardInterrupt:
            save_checkpoint(out_dir, cp)
            print(f"\nINTERRUPTED during {chunk['chunk_id']} — checkpoint saved. "
                  f"Rerun the same command to resume at this chunk.")
            return 3
        except Exception as exc:  # noqa: BLE001 — token expiry lands here
            save_checkpoint(out_dir, cp)
            print(f"\nCHUNK FAILED: {chunk['chunk_id']} — {type(exc).__name__}: {exc}\n"
                  f"Checkpoint saved ({len(cp['completed'])} of {len(plan)} chunks "
                  f"complete). If this is the IAM token expiring (~30 min), "
                  f"refresh it (aws sts get-caller-identity / re-auth SSO) and "
                  f"RERUN THE SAME COMMAND — it resumes at this chunk, never "
                  f"from the start (the session temp tables are re-created "
                  f"automatically).", file=sys.stderr)
            return 3
        secs = round(time.time() - t0, 1)
        cp["completed"][chunk["chunk_id"]] = {
            "rows": n, "seconds": secs, "path": str(out_dir / chunk["out_name"])}
        save_checkpoint(out_dir, cp)
        print(f"[{len(cp['completed'])}/{len(plan)}] {chunk['chunk_id']}: "
              f"{n:,} rows in {secs}s -> {chunk['out_name']}")

    conn.close()
    print(f"\nextraction complete: {len(plan)} chunks in {out_dir}. "
          f"Next: python3 scripts/validate_raw_extracts.py --raw {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Round 1 (schema freeze) task 5 — chunked, resumable PostgreSQL extraction.

    python3 scripts/extract_chunked.py --months 202604,202605,202606 \\
        --advisors-file data/real/cohort.txt [--batch-size 200] \\
        [--out data/real/_raw] [--dry-run] [--restart]

Two hard constraints in the client environment make one-query-for-everything
impossible: a 900-second statement timeout (a single query over four months of
fpic_daily_trade_details_tb_prod — 15M+ rows — WILL exceed it) and a 30-minute
IAM token (even a completing query loses its session on a long extract). So:

- The transaction table extracts in chunks of MONTH x ADVISOR BATCH (default
  200 advisors). Each chunk is its own query and its own CSV:
  ``raw_txn_202604_b001.csv``. Every other table is small enough to be one
  chunk (its own checkpoint entry, same resume behaviour).
- ``extract_checkpoint.json`` (in the output directory) records every
  completed chunk with rows/seconds/path. On ANY error — token expiry
  included — the script saves the checkpoint and exits cleanly with the exact
  resume instruction; rerunning resumes at the first uncompleted chunk, NEVER
  from the start. ``--resume`` is the default; ``--restart`` (explicit) clears
  the checkpoint.
- ``--dry-run`` prints the full chunk plan (and per-month row estimates when a
  connection is available) without extracting anything.

Extraction and ingestion are DECOUPLED: extract everything to CSV, run
scripts/validate_raw_extracts.py, get the operator's review (runbook Phase 4),
and only then load. The CRM export (crm_opportunities.csv) and the four NNM
.txt files are FLAT FILES, not PostgreSQL — this script does not produce them;
place them in the same output directory by hand (see CLIENT_ENV_RUNBOOK.md).

SQL comes from scripts/generate_extraction_sql.templates() — one source of
truth for every SELECT list; the transaction template's date bounds are
re-scoped per month chunk. Connection: set PCE_PG_DSN (or standard PG* env
vars) for psycopg2/psycopg.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_extraction_sql import templates  # noqa: E402

CHECKPOINT_NAME = "extract_checkpoint.json"

# Single-chunk tables, extracted in this order (advisors before transactions so
# a partial run still yields a coherent review set). raw_crm_opportunity.sql is
# EXCLUDED on purpose: the CRM export is a flat file, not a PostgreSQL extract.
SINGLE_TABLES = [
    "raw_advisor_flags.sql", "raw_advisor.sql", "raw_account.sql",
    "raw_product_hierarchy.sql", "raw_rr_changes.sql", "raw_monthly_balance.sql",
    "raw_month_meta.sql", "raw_acct_eci_rel.sql", "raw_acct_eci_map.sql",
    "raw_team_agreement.sql", "raw_adv_flows.sql",
]


def month_bounds(month_id: str) -> tuple[str, str]:
    y, m = int(month_id[:4]), int(month_id[4:6])
    nxt = (y + (m == 12), 1 if m == 12 else m + 1)
    return f"{y:04d}-{m:02d}-01", f"{nxt[0]:04d}-{nxt[1]:02d}-01"


def txn_chunk_sql(sids: list[str], month_id: str) -> str:
    """The transaction template re-scoped to one month x one advisor batch.
    The template carries exactly two DATE literals (the full range); they are
    replaced with the chunk month's bounds — asserted so a template edit that
    changes that shape fails loudly here instead of extracting wrong."""
    sql = templates(sids)["raw_revenue_transaction.sql"]
    dates = re.findall(r"DATE '(\d{4}-\d{2}-\d{2})'", sql)
    if len(dates) != 2:
        raise RuntimeError(
            f"raw_revenue_transaction.sql template no longer carries exactly "
            f"two DATE literals (found {len(dates)}) — update txn_chunk_sql "
            f"before extracting")
    start, end = month_bounds(month_id)
    sql = sql.replace(f"DATE '{dates[0]}'", f"DATE '{start}'", 1)
    sql = sql.replace(f"DATE '{dates[1]}'", f"DATE '{end}'", 1)
    return sql


def build_plan(months: list[str], advisors: list[str], batch_size: int) -> list[dict]:
    """The full chunk plan: single-chunk tables first, then month x batch
    transaction chunks. chunk_id is stable — the checkpoint keys on it."""
    plan = [{"chunk_id": name[:-4], "kind": "table", "sql_name": name,
             "out_name": name[:-4] + ".csv"} for name in SINGLE_TABLES]
    batches = [advisors[i:i + batch_size] for i in range(0, len(advisors), batch_size)]
    for month in months:
        for b, sids in enumerate(batches, start=1):
            plan.append({"chunk_id": f"raw_txn_{month}_b{b:03d}", "kind": "txn",
                         "month": month, "batch_no": b, "sids": sids,
                         "out_name": f"raw_txn_{month}_b{b:03d}.csv"})
    return plan


def plan_fingerprint(months: list[str], advisors: list[str], batch_size: int) -> str:
    basis = json.dumps({"months": months, "advisors": advisors,
                        "batch_size": batch_size}, sort_keys=True)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def load_checkpoint(out_dir: Path) -> dict:
    path = out_dir / CHECKPOINT_NAME
    if path.exists():
        return json.loads(path.read_text())
    return {"fingerprint": None, "completed": {}}


def save_checkpoint(out_dir: Path, cp: dict) -> None:
    (out_dir / CHECKPOINT_NAME).write_text(json.dumps(cp, indent=2))


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


def run_chunk(conn, chunk: dict, months: list[str], advisors: list[str],
              out_dir: Path, statement_timeout: str) -> int:
    if chunk["kind"] == "txn":
        sql = txn_chunk_sql(chunk["sids"], chunk["month"])
    else:
        sql = templates(advisors)[chunk["sql_name"]]
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
                    help="one advisor_sid per line (the cohort, or the full "
                         "book from the sizing query)")
    ap.add_argument("--batch-size", type=int, default=200,
                    help="advisors per transaction chunk (default 200)")
    ap.add_argument("--out", default="data/real/_raw", help="output directory")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the chunk plan (+ row estimates if connected); "
                         "extract nothing")
    ap.add_argument("--restart", action="store_true",
                    help="EXPLICIT full restart: clear the checkpoint first "
                         "(resume is the default)")
    ap.add_argument("--statement-timeout", default="600s",
                    help="per-query statement_timeout (default 600s — inside "
                         "the client's 900s hard limit)")
    args = ap.parse_args(argv)

    months = [m.strip() for m in args.months.split(",") if m.strip()]
    bad = [m for m in months if not re.fullmatch(r"\d{6}", m)]
    if bad:
        print(f"ERROR: month ids must be YYYYMM — got {bad}", file=sys.stderr)
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
    plan = build_plan(months, advisors, args.batch_size)
    fingerprint = plan_fingerprint(months, advisors, args.batch_size)
    n_txn = sum(1 for c in plan if c["kind"] == "txn")
    print(f"chunk plan: {len(SINGLE_TABLES)} single-table chunks + {n_txn} "
          f"transaction chunks ({len(months)} months x "
          f"{(len(advisors) + args.batch_size - 1) // args.batch_size} advisor "
          f"batches of <= {args.batch_size}) = {len(plan)} chunks -> {out_dir}")

    if args.dry_run:
        for c in plan:
            label = (f"{c['chunk_id']}  (month {c['month']}, batch {c['batch_no']}: "
                     f"{len(c['sids'])} advisors)" if c["kind"] == "txn"
                     else c["chunk_id"])
            print(f"  {label}  -> {c['out_name']}")
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
                print(f"  estimated transaction rows {month}: {cur.fetchone()[0]:,}")
            conn.close()
        except Exception as exc:  # noqa: BLE001 — estimates are optional in dry-run
            estimate_err = f"{type(exc).__name__}: {exc}"
        if estimate_err:
            print(f"  row estimates unavailable (no connection): {estimate_err}")
        print("dry run — nothing extracted.")
        return 0

    cp = load_checkpoint(out_dir)
    if args.restart:
        print("--restart: clearing checkpoint (full re-extract)")
        cp = {"fingerprint": fingerprint, "completed": {}}
        save_checkpoint(out_dir, cp)
    elif cp["fingerprint"] and cp["fingerprint"] != fingerprint:
        print(f"ERROR: checkpoint in {out_dir} was written for a DIFFERENT plan "
              f"(months/advisors/batch changed). Rerun with the original "
              f"arguments to resume it, or pass --restart to discard it.",
              file=sys.stderr)
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
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not connect to PostgreSQL: {exc}\n"
              f"Set PCE_PG_DSN (or PG* env vars), refresh the IAM token if "
              f"expired, then rerun the same command — completed chunks are "
              f"checkpointed and will be skipped.", file=sys.stderr)
        return 2

    for i, chunk in enumerate(todo, start=1):
        t0 = time.time()
        try:
            n = run_chunk(conn, chunk, months, advisors, out_dir,
                          args.statement_timeout)
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
                  f"from the start.", file=sys.stderr)
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

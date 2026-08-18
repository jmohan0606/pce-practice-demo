"""Round 5 task 1 — build data/real/cohort.txt from the CLIENT'S cohort query.

    python3 scripts/build_cohort.py [--out data/real/cohort.txt] [--print-sql]
                                    [--allow-count-mismatch]

Replaces scripts/select_cohort.py (RETIRED): the cohort is no longer selected
by scenario coverage — the client DEFINES it (requirements of 17 Aug 2026).
This script runs their query verbatim and writes one advisor_sid per line.

Expected: 5,455 distinct advisors. A different count means a filter was
transcribed wrongly — the script REPORTS the actual number and STOPS without
writing unless --allow-count-mismatch is passed (an operator decision, made
knowingly, after the client confirms the population moved).

The reference tables (fpic_prm_rr_tb, fpic_employee_tb) are used HERE and only
here to resolve the advisor list. They are NEVER joined to the trade table —
one employee has one row per branch and location, so such a join both drops
unmatched transactions and multiplies matched ones (the 4.1M-row loss).
Downstream, every transaction extract applies the cohort via
``advisor_sid IN (SELECT advisor_sid FROM cohort_adv)``.

Connection: PCE_PG_DSN / standard PG* env vars (same as extract_chunked.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPECTED_COHORT_COUNT = 5455

# The client's definition, verbatim (docs/spec/CLIENT_REQUIREMENTS_2026_08_17.md
# §1). Do not adjust it.
COHORT_SQL = """\
SELECT DISTINCT r.standard_id
FROM   pcr.fpic_prm_rr_tb r
INNER JOIN pcr.fpic_employee_tb e ON r.standard_id = e.em_standard_id
WHERE  r.prm_ofc_no = '731'
  AND  r.cwm_comply_posn_cd IN ('D','I','')
  AND  r.dist_channel_typ NOT IN ('JPMPAP','JPMPAD','JPMIDTL','JPMIDFA','JPMPAPTL')
  AND  e.job_cd IN ('HK0058','HK0059','HK0176','HK0183','HK0184','HK0185',
                    'HK0186','HK0187','HK0188','HK0280','HK0286','HK0289')
  AND  e.em_status_cd IN ('A','L','T')
ORDER  BY r.standard_id"""


def default_connect():
    """psycopg2 (or psycopg 3) via PCE_PG_DSN / standard PG* env vars."""
    import os
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


def main(argv: list[str] | None = None, connect=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/real/cohort.txt")
    ap.add_argument("--print-sql", action="store_true",
                    help="print the client's cohort query and exit (for a "
                         "human session; no connection needed)")
    ap.add_argument("--allow-count-mismatch", action="store_true",
                    help="write cohort.txt even when the count is not "
                         f"{EXPECTED_COHORT_COUNT:,} (operator override — the "
                         "client has confirmed the population moved)")
    args = ap.parse_args(argv)

    if args.print_sql:
        print(COHORT_SQL + ";")
        return 0

    try:
        conn = (connect or default_connect)()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not connect to PostgreSQL: {exc}\n"
              f"Set PCE_PG_DSN (or PG* env vars), refresh the IAM token if "
              f"expired, then rerun. (--print-sql prints the query for a "
              f"manual session.)", file=sys.stderr)
        return 2

    cur = conn.cursor()
    cur.execute("SET statement_timeout = '600s'")
    cur.execute(COHORT_SQL)
    sids = [str(row[0]).strip() for row in cur.fetchall() if str(row[0]).strip()]
    conn.close()

    n = len(sids)
    print(f"cohort query returned {n:,} distinct advisors "
          f"(expected {EXPECTED_COHORT_COUNT:,})")
    if n != EXPECTED_COHORT_COUNT and not args.allow_count_mismatch:
        print(f"STOP: count differs from the client's stated "
              f"{EXPECTED_COHORT_COUNT:,} — a different number means a filter "
              f"was transcribed wrongly. Nothing was written. Report the "
              f"actual number ({n:,}) to the client; once they confirm the "
              f"population moved, rerun with --allow-count-mismatch.",
              file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sids) + "\n", encoding="utf-8")
    print(f"wrote {out} ({n:,} advisor SIDs, one per line)")
    print("next: python3 scripts/generate_extraction_sql.py  (regenerates the "
          "extraction SQL against the new cohort)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

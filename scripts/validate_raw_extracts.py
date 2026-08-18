#!/usr/bin/env python3
"""Round 1 task 5 / Round 2a task 2 — validate the raw extract drop BEFORE loading.

    python3 scripts/validate_raw_extracts.py [--raw data/real/_raw]

Runs against the ONE raw directory and checks ALL THREE source kinds — the
chunked PostgreSQL extracts (raw_*.csv), the four NNM .txt files, and the CRM
opportunity export — because a PostgreSQL-only validation would pass a drop
that loads silently incomplete.

Round 2a: chunk awareness covers ALL FIVE families (transactions, monthly
balances, account, acct_eci_rel, acct_eci_map), not transactions alone — a
missing acct_eci_rel bucket fails V-2 exactly as a missing transaction batch
does. Transactions stream through the checks (12.4M rows never sit in memory).

Checks:
  V-0  NO transaction SQL joins the reference tables (fpic_prm_rr_tb /
       fpic_employee_tb) — they carry one row per branch/location, so a join
       to the trade table drops unmatched rows AND multiplies matched ones
       (the mistake that cost 4.1M rows and a full re-extraction). The cohort
       is applied via IN (SELECT ... FROM cohort_adv), never a join.
  V-1  the three source kinds detected (all four NNM categories present, CRM
       export present, no ambiguous duplicates, no gap in any chunk family's
       sequence) — build_real_data.detect_sources
  V-2  every chunk family: sequence complete; when extract_checkpoint.json
       exists, every completed chunk's file exists and its row count matches
       the checkpoint's record — for ALL families, not transactions alone
  V-3  RAW_CONTRACT column check on every PostgreSQL csv (every chunk of every
       family individually)
  V-4  the NNM files PARSE (parse_nnm is loud) with rows in every category
  V-5  CRM export columns + row count
  V-6  account keys normalise cleanly (no empties, no collisions)
  V-7  reason_cd: blank is the only "none" spelling in the raw feed
  V-8  every transaction month (from proc_dt — Round 5) appears in
       raw_month_meta.csv and vice versa;
       when balances arrive as per-month chunks, their months must match too
  V-9  unmapped product codes listed with counts — silence is not allowed
  V-10 THE SANITY ANCHOR: credited revenue per cohort advisor per month is
       roughly $33k firmwide.

Exit 0 = safe to proceed to the Phase 4 review gate. Exit 1 = fix the extract
first; loading is not safe.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.ids import normalize_account_key  # noqa: E402
from scripts import parse_nnm  # noqa: E402
from scripts.build_real_data import (  # noqa: E402
    CHUNK_FAMILIES, CRM_LEGACY_NAME, RAW_CONTRACT, ColumnMismatchError,
    detect_sources, family_files, iter_csv_rows,
)

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        return header, [{(k or "").strip(): (v or "").strip()
                         for k, v in row.items() if k} for row in reader]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default="data/real/_raw", help="raw extract directory")
    args = ap.parse_args()
    raw_dir = Path(args.raw)
    if not raw_dir.is_dir():
        print(f"ERROR: {raw_dir} is not a directory", file=sys.stderr)
        return 1

    # V-0 — no reference-table join in any generated transaction SQL. This
    # guards the GENERATOR, not the drop: the join that caused the 4.1M-row
    # loss must never silently reappear in a template edit. Checks the
    # template AND a real chunk (what actually runs against the database).
    from scripts.generate_extraction_sql import templates as _templates
    from scripts.extract_chunked import txn_chunk_sql as _txn_chunk_sql

    ref_join = re.compile(
        r"JOIN\s+(pcr\.)?(fpic_prm_rr_tb|fpic_employee_tb)", re.IGNORECASE)
    txn_sqls = {
        "raw_revenue_transaction.sql template":
            _templates()["raw_revenue_transaction.sql"],
        "txn chunk SQL (sample)": _txn_chunk_sql(["T000001"], "202604"),
    }
    joined = [name for name, sql in txn_sqls.items() if ref_join.search(sql)]
    check("V-0 no transaction SQL joins fpic_prm_rr_tb/fpic_employee_tb "
          "(cohort via IN (SELECT ...), never a join)", not joined,
          f"reference-table JOIN found in: {joined} — this is the 4.1M-row "
          f"bug; use advisor_sid IN (SELECT advisor_sid FROM cohort_adv)"
          if joined else "template + sample chunk clean")

    # V-1 — three source kinds (detect_sources also sequence-checks every
    # chunk family and refuses ambiguous both-forms drops)
    try:
        sources = detect_sources(raw_dir)
        chunked = {f: c for f, c in sources["chunks"].items() if c}
        check("V-1 three source kinds detected",
              True, "PostgreSQL raw_*.csv"
                    + (" (chunked: " + ", ".join(f"{f}={len(c)}"
                       for f, c in chunked.items()) + ")" if chunked else "")
                    + f", NNM {sources['nnm_files']}, CRM {sources['crm_file']}")
    except ColumnMismatchError as exc:
        check("V-1 three source kinds detected", False, str(exc))
        print(f"\n{len(FAILURES)} failure(s) — fix the drop before loading.")
        return 1

    # V-2 — chunk sequence + checkpoint agreement, ALL FIVE families
    any_chunks = any(sources["chunks"].values())
    if any_chunks:
        seq_desc = []
        for family, chunks in sources["chunks"].items():
            if not chunks:
                continue
            spec = CHUNK_FAMILIES[family]
            if spec["sequenced"] == "per_month":
                by_month = collections.defaultdict(list)
                for p in chunks:
                    m = spec["regex"].fullmatch(p.name)
                    by_month[m.group(1)].append(int(m.group(2)))
                seq_desc.append(", ".join(f"{mo}: b001..b{max(b):03d}"
                                          for mo, b in sorted(by_month.items())))
            elif spec["sequenced"] == "months":
                months = sorted(spec["regex"].fullmatch(p.name).group(1)
                                for p in chunks)
                seq_desc.append(f"balances: {months}")
            else:
                nums = sorted(int(spec["regex"].fullmatch(p.name).group(1))
                              for p in chunks)
                seq_desc.append(f"{family[:-4]}: b001..b{max(nums):03d}")
        check("V-2 chunk sequences have no gaps (all five families)", True,
              "; ".join(seq_desc))
        cp_path = raw_dir / "extract_checkpoint.json"
        if cp_path.exists():
            cp = json.loads(cp_path.read_text())
            problems = []
            checkpointed = set()
            for chunk_id, rec in cp.get("completed", {}).items():
                f = raw_dir / f"{chunk_id}.csv"
                checkpointed.add(chunk_id)
                if not f.exists():
                    problems.append(f"{chunk_id}: checkpointed but file missing")
                    continue
                n = sum(1 for _ in f.open()) - 1
                if n != rec.get("rows"):
                    problems.append(f"{chunk_id}: file has {n} rows, "
                                    f"checkpoint recorded {rec.get('rows')}")
            on_disk = {p.stem for chunks in sources["chunks"].values()
                       for p in chunks}
            unknown = sorted(on_disk - checkpointed)
            if unknown:
                problems.append(f"chunk files not in the checkpoint: {unknown}")
            check("V-2 chunk files match extract_checkpoint.json (all families)",
                  not problems,
                  "; ".join(problems) if problems
                  else f"{len(checkpointed)} checkpointed chunks verified "
                       f"(rows + existence)")
        else:
            print("      (no extract_checkpoint.json — chunk/row cross-check skipped)")
    else:
        print("      (no chunk files — single-file drop, no sequences to check)")

    # V-3 — RAW_CONTRACT columns on every PostgreSQL file, every chunk
    # individually. Transactions STREAM through the row-level accumulators
    # used by V-7/8/9/10 (never held in memory).
    col_problems: list[str] = []
    n_files_checked = 0
    txn_months: collections.Counter = collections.Counter()
    txn_credited_by_month: collections.Counter = collections.Counter()
    literal_none = blanks = 0
    coded: collections.Counter = collections.Counter()
    unmapped: collections.Counter = collections.Counter()
    known: set = set()
    try:
        hierarchy = list(iter_csv_rows(raw_dir / "raw_product_hierarchy.csv",
                                       RAW_CONTRACT["raw_product_hierarchy.csv"]))
        known = {(h["product_cd"], h["product_sub_cd"]) for h in hierarchy}
    except (ColumnMismatchError, FileNotFoundError) as exc:
        col_problems.append(str(exc))

    for family in RAW_CONTRACT:
        if family == CRM_LEGACY_NAME:
            continue  # V-5 checks the CRM export under its detected name
        try:
            files = (family_files(raw_dir, sources, family)
                     if family in CHUNK_FAMILIES else [raw_dir / family])
            for path in files:
                if not path.exists():
                    col_problems.append(f"{family}: missing")
                    continue
                n_files_checked += 1
                if family == "raw_revenue_transaction.csv":
                    for t in iter_csv_rows(path, RAW_CONTRACT[family]):
                        month = (t.get("proc_dt") or "")[:7].replace("-", "")  # Round 5: proc month
                        if month:
                            txn_months[month] += 1
                        reason = (t.get("reason_cd") or "").strip()
                        if reason == "__NONE__":
                            literal_none += 1
                        elif not reason:
                            blanks += 1
                            txn_credited_by_month[month] += 0
                        if not reason:
                            txn_credited_by_month[month] += float(
                                t.get("post_split_credited_amt") or 0)
                        else:
                            coded[reason] += 1
                        key = (t.get("product_cd", ""), t.get("product_sub_cd", ""))
                        if key not in known:
                            unmapped[key] += 1
                else:
                    # header contract only (row checks belong to the build)
                    next(iter_csv_rows(path, RAW_CONTRACT[family]), None)
        except ColumnMismatchError as exc:
            col_problems.append(str(exc))
    check("V-3 RAW_CONTRACT columns on every PostgreSQL file (every chunk "
          "individually)", not col_problems,
          "; ".join(col_problems) if col_problems
          else f"{n_files_checked} file(s) checked across "
               f"{len(RAW_CONTRACT) - 1} contracts")

    # V-4 — the NNM files parse
    try:
        nnm_rows = parse_nnm.parse_nnm_dir(raw_dir)
        by_cat = collections.Counter(r["category"] for r in nnm_rows)
        missing_cats = [c for c in ("EC", "NB", "YI", "FS") if not by_cat.get(c)]
        check("V-4 NNM files parse with rows in all four categories",
              not missing_cats,
              f"empty categories: {missing_cats}" if missing_cats
              else ", ".join(f"{c}: {n}" for c, n in sorted(by_cat.items())))
    except Exception as exc:  # noqa: BLE001 — parse_nnm raises loudly by design
        check("V-4 NNM files parse with rows in all four categories", False,
              f"{type(exc).__name__}: {exc}")

    # V-5 — CRM export
    crm_header, crm_rows = read_csv(raw_dir / sources["crm_file"])
    crm_missing = [c for c in RAW_CONTRACT[CRM_LEGACY_NAME] if c not in crm_header]
    check("V-5 CRM export columns + rows", not crm_missing and bool(crm_rows),
          f"missing columns {crm_missing}" if crm_missing
          else f"{sources['crm_file']}: {len(crm_rows)} rows")

    # V-6 — account keys normalise cleanly (streams the account family)
    padded = n_accounts = 0
    emptied: list[str] = []
    norm_counts: collections.Counter = collections.Counter()
    for path in family_files(raw_dir, sources, "raw_account.csv"):
        for a in iter_csv_rows(path, RAW_CONTRACT["raw_account.csv"]):
            n_accounts += 1
            k = normalize_account_key(a["account_no"])
            if a["account_no"] != k:
                padded += 1
            if not k:
                emptied.append(a["account_no"])
            else:
                norm_counts[k] += 1
    collisions = sorted(k for k, n in norm_counts.items() if n > 1)
    check("V-6 account keys normalise cleanly (no empties, no collisions)",
          not emptied and not collisions,
          f"emptied={emptied[:3]} collisions={collisions[:3]}"
          if emptied or collisions
          else f"{n_accounts} accounts, {padded} padded (normalised at build)")

    # V-7 — reason_cd spelling (accumulated during the V-3 stream)
    check("V-7 reason_cd: blank is the only 'none' spelling in raw",
          literal_none == 0,
          f"{literal_none} rows already carry the literal '__NONE__' — the "
          f"build would double-map" if literal_none
          else f"{blanks} blank (-> __NONE__ at build); coded: {dict(coded)}")

    # V-8 — months agree between transactions, month meta, and balance chunks
    _, meta = read_csv(raw_dir / "raw_month_meta.csv")
    meta_months = {m["month_id"] for m in meta}
    only_txn = sorted(set(txn_months) - meta_months)
    only_meta = sorted(meta_months - set(txn_months))
    bal_chunks = sources["chunks"]["raw_monthly_balance.csv"]
    bal_note = ""
    bal_ok = True
    if bal_chunks:
        bal_months = {re.fullmatch(r"raw_balance_(\d{6})\.csv", p.name).group(1)
                      for p in bal_chunks}
        missing_bal = sorted(meta_months - bal_months)
        if missing_bal:
            bal_ok = False
            bal_note = f"; balance chunk missing for month(s) {missing_bal}"
        else:
            bal_note = f"; balance chunks cover {sorted(bal_months)}"
    check("V-8 transaction months == month-meta months (+ balance chunk coverage)",
          not only_txn and not only_meta and bal_ok,
          (f"txn-only={only_txn} meta-only={only_meta}{bal_note}"
           if only_txn or only_meta or not bal_ok
           else ", ".join(f"{m}: {n:,} rows"
                          for m, n in sorted(txn_months.items())) + bal_note))

    # V-9 — unmapped product codes, listed with counts
    print("      unmapped product codes: "
          + (", ".join(f"{cd}/{sub}: {n}" for (cd, sub), n in unmapped.most_common())
             if unmapped else "none — every txn code is in the hierarchy"))
    check("V-9 unmapped product codes listed (silence not allowed)", True,
          f"{len(unmapped)} distinct unmapped code(s)")

    # V-10 — the sanity anchor (credited totals accumulated during the stream)
    _, advisors = read_csv(raw_dir / "raw_advisor.csv")
    cohort = sum(1 for a in advisors
                 if str(a.get("in_cohort", "")).strip().lower() in ("true", "t", "1"))
    months_n = max(len(txn_months), 1)
    credited = sum(txn_credited_by_month.values())
    per_advisor_month = credited / max(cohort, 1) / months_n
    anchor_ok = 6_600 <= per_advisor_month <= 165_000  # $33k within 5x either way
    check("V-10 sanity anchor: ~$33k credited per cohort advisor per month",
          anchor_ok,
          f"${per_advisor_month:,.0f}/advisor/month over {cohort} cohort "
          f"advisors x {months_n} months"
          + ("" if anchor_ok else
             " — ORDER OF MAGNITUDE OUT: check the proc_dt scope bounds and "
             "that no team-agreement join fanned rows out"))

    print(f"\n{len(FAILURES)} failure(s)" + (" — fix the extract before loading."
                                             if FAILURES else
                                             " — safe to proceed to the Phase 4 "
                                             "review gate (send this output)."))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

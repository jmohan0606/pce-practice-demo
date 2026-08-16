#!/usr/bin/env python3
"""Round 1 (schema freeze) task 5 — validate the raw extract drop BEFORE loading.

    python3 scripts/validate_raw_extracts.py [--raw data/real/_raw]

Runs against the ONE raw directory and checks ALL THREE source kinds — the
chunked PostgreSQL extracts (raw_*.csv), the four NNM .txt files, and the CRM
opportunity export — because a PostgreSQL-only validation would pass a drop
that loads silently incomplete.

Checks:
  V-1  the three source kinds detected (all four NNM categories present, CRM
       export present, no ambiguous duplicates) — build_real_data.detect_sources
  V-2  transaction chunks: no gaps in the batch sequence per month; when
       extract_checkpoint.json exists, every planned chunk completed and each
       file's row count matches the checkpoint's record
  V-3  RAW_CONTRACT column check on every PostgreSQL csv (chunks included)
  V-4  the NNM files PARSE (parse_nnm is loud: header/format/duplicates) with
       rows in every category
  V-5  CRM export columns + row count
  V-6  account keys normalise cleanly — normalize_account_key never empties a
       key and never collides two accounts (padded keys are fine; the build
       normalises them — the count is reported)
  V-7  reason_cd: blank is the only "none" spelling in the raw feed (build
       maps blank -> __NONE__); a literal '__NONE__' in raw would double-map
  V-8  every transaction month appears in raw_month_meta.csv and vice versa,
       with per-month row counts printed for review
  V-9  unmapped product codes (txn codes absent from raw_product_hierarchy)
       listed with counts — zero required rows, but silence is not allowed
  V-10 THE SANITY ANCHOR: credited revenue per cohort advisor per month is
       roughly $33k firmwide. An order of magnitude out means proc_dt was
       used instead of trade_dt, or the team-agreement join fanned out.

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
    CRM_LEGACY_NAME, RAW_CONTRACT, ColumnMismatchError, detect_sources,
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

    # V-1 — three source kinds
    try:
        sources = detect_sources(raw_dir)
        check("V-1 three source kinds detected",
              True, f"PostgreSQL raw_*.csv"
                    f"{' (' + str(len(sources['txn_chunks'])) + ' txn chunks)' if sources['txn_chunks'] else ''}, "
                    f"NNM {sources['nnm_files']}, CRM {sources['crm_file']}")
    except ColumnMismatchError as exc:
        check("V-1 three source kinds detected", False, str(exc))
        print(f"\n{len(FAILURES)} failure(s) — fix the drop before loading.")
        return 1

    # V-2 — chunk sequence + checkpoint agreement
    chunks = sources["txn_chunks"]
    if chunks:
        by_month: dict[str, list[int]] = collections.defaultdict(list)
        for p in chunks:
            m = re.fullmatch(r"raw_txn_(\d{6})_b(\d+)\.csv", p.name)
            if m:
                by_month[m.group(1)].append(int(m.group(2)))
        gaps = {month: sorted(set(range(1, max(batches) + 1)) - set(batches))
                for month, batches in by_month.items()}
        gaps = {m: g for m, g in gaps.items() if g}
        check("V-2 transaction chunk sequence has no gaps", not gaps,
              f"missing batches: {gaps}" if gaps
              else ", ".join(f"{m}: b001..b{max(b):03d}" for m, b in sorted(by_month.items())))
        cp_path = raw_dir / "extract_checkpoint.json"
        if cp_path.exists():
            cp = json.loads(cp_path.read_text())
            problems = []
            for chunk_id, rec in cp.get("completed", {}).items():
                if not chunk_id.startswith("raw_txn_"):
                    continue
                f = raw_dir / f"{chunk_id}.csv"
                if not f.exists():
                    problems.append(f"{chunk_id}: checkpointed but file missing")
                    continue
                n = sum(1 for _ in f.open()) - 1
                if n != rec.get("rows"):
                    problems.append(f"{chunk_id}: file has {n} rows, "
                                    f"checkpoint recorded {rec.get('rows')}")
            planned_txn = [c for c in cp.get("completed", {}) if c.startswith("raw_txn_")]
            on_disk = {p.stem for p in chunks}
            unknown = sorted(on_disk - set(planned_txn))
            if unknown:
                problems.append(f"chunk files not in the checkpoint: {unknown}")
            check("V-2 chunk files match extract_checkpoint.json", not problems,
                  "; ".join(problems) if problems
                  else f"{len(planned_txn)} txn chunks verified")
        else:
            print("      (no extract_checkpoint.json — chunk/row cross-check skipped)")
    else:
        print("      (single raw_revenue_transaction.csv — no chunk sequence to check)")

    # V-3 — RAW_CONTRACT columns on every PostgreSQL csv
    txn_expected = RAW_CONTRACT["raw_revenue_transaction.csv"]
    txns: list[dict] = []
    col_problems: list[str] = []
    for name, expected in RAW_CONTRACT.items():
        if name == "raw_revenue_transaction.csv" and chunks:
            continue  # chunks checked below
        if name == CRM_LEGACY_NAME:
            continue  # V-5 checks the CRM export under its detected name
        path = raw_dir / name
        if not path.exists():
            col_problems.append(f"{name}: missing")
            continue
        header, rows = read_csv(path)
        missing = [c for c in expected if c not in header]
        if missing:
            col_problems.append(f"{name}: missing columns {missing}")
        if name == "raw_revenue_transaction.csv":
            txns = rows
    for p in chunks:
        header, rows = read_csv(p)
        missing = [c for c in txn_expected if c not in header]
        if missing:
            col_problems.append(f"{p.name}: missing columns {missing}")
        txns.extend(rows)
    check("V-3 RAW_CONTRACT columns on every PostgreSQL file", not col_problems,
          "; ".join(col_problems) if col_problems
          else f"{len(RAW_CONTRACT) - 1} contracts + {len(chunks)} chunk files")

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

    # V-6 — account keys normalise cleanly
    _, accounts = read_csv(raw_dir / "raw_account.csv")
    padded = sum(1 for a in accounts
                 if a["account_no"] != normalize_account_key(a["account_no"]))
    emptied = [a["account_no"] for a in accounts
               if not normalize_account_key(a["account_no"])]
    norm_counts = collections.Counter(
        normalize_account_key(a["account_no"]) for a in accounts)
    collisions = sorted(k for k, n in norm_counts.items() if n > 1)
    check("V-6 account keys normalise cleanly (no empties, no collisions)",
          not emptied and not collisions,
          f"emptied={emptied[:3]} collisions={collisions[:3]}"
          if emptied or collisions
          else f"{len(accounts)} accounts, {padded} padded (normalised at build)")

    # V-7 — reason_cd spelling
    literal_none = sum(1 for t in txns if t.get("reason_cd") == "__NONE__")
    blanks = sum(1 for t in txns if not (t.get("reason_cd") or "").strip())
    coded = collections.Counter((t.get("reason_cd") or "").strip()
                                for t in txns if (t.get("reason_cd") or "").strip())
    check("V-7 reason_cd: blank is the only 'none' spelling in raw",
          literal_none == 0,
          f"{literal_none} rows already carry the literal '__NONE__' — the "
          f"build would double-map" if literal_none
          else f"{blanks} blank (-> __NONE__ at build); coded: {dict(coded)}")

    # V-8 — months agree between transactions and month meta
    _, meta = read_csv(raw_dir / "raw_month_meta.csv")
    meta_months = {m["month_id"] for m in meta}
    txn_months = collections.Counter(
        (t.get("trade_dt") or "")[:7].replace("-", "") for t in txns)
    txn_months.pop("", None)
    only_txn = sorted(set(txn_months) - meta_months)
    only_meta = sorted(meta_months - set(txn_months))
    check("V-8 transaction months == month-meta months", not only_txn and not only_meta,
          f"txn-only={only_txn} meta-only={only_meta}" if only_txn or only_meta
          else ", ".join(f"{m}: {n:,} rows" for m, n in sorted(txn_months.items())))

    # V-9 — unmapped product codes, listed with counts
    _, hierarchy = read_csv(raw_dir / "raw_product_hierarchy.csv")
    known = {(h["product_cd"], h["product_sub_cd"]) for h in hierarchy}
    unmapped = collections.Counter(
        (t.get("product_cd", ""), t.get("product_sub_cd", "")) for t in txns
        if (t.get("product_cd", ""), t.get("product_sub_cd", "")) not in known)
    print(f"      unmapped product codes: "
          + (", ".join(f"{cd}/{sub}: {n}" for (cd, sub), n in unmapped.most_common())
             if unmapped else "none — every txn code is in the hierarchy"))
    check("V-9 unmapped product codes listed (silence not allowed)", True,
          f"{len(unmapped)} distinct unmapped code(s)")

    # V-10 — the sanity anchor
    _, advisors = read_csv(raw_dir / "raw_advisor.csv")
    cohort = sum(1 for a in advisors
                 if str(a.get("in_cohort", "")).strip().lower() in ("true", "t", "1"))
    months_n = max(len(txn_months), 1)
    credited = sum(float(t.get("post_split_credited_amt") or 0) for t in txns
                   if not (t.get("reason_cd") or "").strip())
    per_advisor_month = credited / max(cohort, 1) / months_n
    anchor_ok = 6_600 <= per_advisor_month <= 165_000  # $33k within 5x either way
    check("V-10 sanity anchor: ~$33k credited per cohort advisor per month",
          anchor_ok,
          f"${per_advisor_month:,.0f}/advisor/month over {cohort} cohort "
          f"advisors x {months_n} months"
          + ("" if anchor_ok else
             " — ORDER OF MAGNITUDE OUT: check that trade_dt (not proc_dt) "
             "scoped the extract and that no team-agreement join fanned rows out"))

    print(f"\n{len(FAILURES)} failure(s)" + (" — fix the extract before loading."
                                             if FAILURES else
                                             " — safe to proceed to the Phase 4 "
                                             "review gate (send this output)."))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

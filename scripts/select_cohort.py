"""Round F task 4.1 — pick the 20-advisor extraction cohort from raw_advisor_flags.csv.

    python3 scripts/select_cohort.py [--flags data/real/_raw/raw_advisor_flags.csv]
                                     [--out data/real/cohort.txt] [--yes]

Selection order (ROUND_D_EXTRACTION.md §4 step 1 / ROUND_F_SPEC 4.1):
  1. EVERY advisor with has_recorded_grid_reduction, up to 5 (by revenue).
     Only ~99 accounts firmwide carry one — missing them kills the app's single
     best insight (the expected-vs-recorded grid-reduction finding).
  2. Greedy coverage of the remaining eight flags (most still-uncovered flags
     first; revenue breaks ties).
  3. Fill to 20 by highest total credited revenue.
  4. Deliberately include 2-3 advisors with NO flags — a cohort where every
     advisor has a dramatic story does not read as real data.

Prints the coverage matrix and requires confirmation before writing cohort.txt
(--yes skips the prompt for non-interactive runs).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_real_data import FLAG_COLUMNS, as_bool, num, read_raw  # noqa: E402

COHORT_SIZE = 20
GRID_REDUCTION_CAP = 5
NO_FLAG_TARGET = 3  # aim for 3, accept 2 (spec: "2-3")
NO_FLAG_MIN = 2


def select(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Returns (selected rows in selection order, per-row reason tags)."""
    for r in rows:
        r["_rev"] = num(r["total_credited_amt"])
        r["_flags"] = {f for f in FLAG_COLUMNS if as_bool(r.get(f, ""))}
    by_rev = sorted(rows, key=lambda r: -r["_rev"])

    selected: list[dict] = []
    reasons: list[str] = []
    picked: set[str] = set()

    def take(r: dict, reason: str) -> None:
        selected.append(r)
        reasons.append(reason)
        picked.add(r["advisor_sid"])

    # 1 — grid reduction first (scarce; up to 5, richest first)
    for r in by_rev:
        if len([x for x in reasons if x == "grid_reduction"]) >= GRID_REDUCTION_CAP:
            break
        if as_bool(r.get("has_recorded_grid_reduction", "")):
            take(r, "grid_reduction")

    # 2 — greedy coverage of the remaining eight flags
    other_flags = [f for f in FLAG_COLUMNS if f != "has_recorded_grid_reduction"]
    covered = {f for r in selected for f in r["_flags"]}
    while len(selected) < COHORT_SIZE - NO_FLAG_TARGET:
        best, best_gain = None, 0
        for r in by_rev:
            if r["advisor_sid"] in picked:
                continue
            gain = len((r["_flags"] & set(other_flags)) - covered)
            if gain > best_gain:
                best, best_gain = r, gain
        if best is None:
            break  # nothing adds coverage
        take(best, f"coverage(+{best_gain})")
        covered |= best["_flags"]

    # 4 (reserved before 3) — 2-3 advisors with NO flags, richest first
    no_flag = [r for r in by_rev if not r["_flags"] and r["advisor_sid"] not in picked]
    for r in no_flag[:NO_FLAG_TARGET]:
        if len(selected) >= COHORT_SIZE:
            break
        take(r, "no_flags")

    # 3 — fill to 20 by highest credited revenue
    for r in by_rev:
        if len(selected) >= COHORT_SIZE:
            break
        if r["advisor_sid"] not in picked:
            take(r, "top_revenue")

    n_no_flag = sum(1 for x in reasons if x == "no_flags")
    if n_no_flag < NO_FLAG_MIN:
        print(f"WARNING: only {n_no_flag} no-flag advisors available "
              f"(wanted {NO_FLAG_MIN}-{NO_FLAG_TARGET})")
    return selected, reasons


def print_matrix(selected: list[dict], reasons: list[str]) -> None:
    short = [f.replace("has_", "")[:14] for f in FLAG_COLUMNS]
    print("\nCOVERAGE MATRIX (x = flag set)")
    header = f"{'advisor_sid':<12} {'revenue':>14}  " + " ".join(f"{s:<14}" for s in short) + "  reason"
    print(header)
    print("-" * len(header))
    for r, why in zip(selected, reasons):
        cells = " ".join(f"{'x' if f in r['_flags'] else '.':<14}" for f in FLAG_COLUMNS)
        print(f"{r['advisor_sid']:<12} {r['_rev']:>14,.2f}  {cells}  {why}")
    covered = {f for r in selected for f in r["_flags"]}
    missing = [f for f in FLAG_COLUMNS if f not in covered]
    print(f"\nflags covered: {len(covered)}/{len(FLAG_COLUMNS)}"
          + (f"  MISSING: {missing}" if missing else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flags", default="data/real/_raw/raw_advisor_flags.csv")
    ap.add_argument("--out", default="data/real/cohort.txt")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt (non-interactive runs)")
    args = ap.parse_args()

    flags_path = Path(args.flags)
    rows = read_raw(flags_path.parent, flags_path.name)
    print(f"{len(rows)} candidate advisors read from {flags_path}")

    selected, reasons = select(rows)
    print_matrix(selected, reasons)

    if len(selected) < COHORT_SIZE:
        print(f"WARNING: only {len(selected)} advisors available (wanted {COHORT_SIZE})")

    if not args.yes:
        answer = input(f"\nWrite {len(selected)} advisor SIDs to {args.out}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("aborted — cohort.txt not written")
            return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"{r['advisor_sid']}\n" for r in selected), encoding="utf-8")
    print(f"wrote {out} ({len(selected)} SIDs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

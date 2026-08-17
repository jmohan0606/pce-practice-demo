#!/usr/bin/env python3
"""Round 4 task 7 — generate the PRACTICE-LEVEL insight run from the terminal.

    python3 scripts/generate_practice_insights.py --from 202604 --to 202605
    python3 scripts/generate_practice_insights.py --all-transitions

One run per transition (advisor="all" with practice_only — the aggregate book
run only, never the 21-run cohort fan-out the UI button does).
--all-transitions derives every consecutive month pair from the month
vertices. Resumable, cost-projected, skip-existing, failure-isolated —
scripts/_generate_insights_common.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _generate_insights_common import (  # noqa: E402
    GenError,
    add_common_args,
    check_prerequisites,
    confirm_or_exit,
    consecutive_transitions,
    cost_projection,
    run_targets,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_month", help="from month, YYYYMM")
    parser.add_argument("--to", dest="to_month", help="to month, YYYYMM")
    parser.add_argument("--all-transitions", action="store_true",
                        help="every consecutive month pair from the month vertices")
    add_common_args(parser)
    args = parser.parse_args()

    try:
        prereqs = check_prerequisites(require_real=args.require_real)
        if args.all_transitions:
            pairs = consecutive_transitions()
            if not pairs:
                raise GenError("fewer than two months loaded — no transition to run")
        elif args.from_month and args.to_month:
            pairs = [(args.from_month, args.to_month)]
        else:
            parser.error("give --from and --to, or --all-transitions")
        version_id = args.version_id or prereqs["published_version_id"]

        targets = [{"key": f"practice|{f}|{t}|{version_id}",
                    "label": f"practice {f} -> {t}",
                    "advisor": "all", "from": f, "to": t,
                    "practice_only": True}
                   for f, t in pairs]
        confirm_or_exit(
            f"{len(targets)} practice run(s) on {version_id}\n"
            + cost_projection(len(targets)), args.yes)
        return run_targets("practice", targets, args, version_id)
    except GenError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Round 4 task 9 — generate ONE advisor's insight run from the terminal.

    python3 scripts/generate_advisor_insights.py --advisor V000014 --from 202604 --to 202605

An unknown SID fails immediately — before any LLM call.
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
    api_get,
    check_prerequisites,
    confirm_or_exit,
    cost_projection,
    run_targets,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--advisor", required=True, help="advisor SID, e.g. V000014")
    parser.add_argument("--from", dest="from_month", required=True)
    parser.add_argument("--to", dest="to_month", required=True)
    add_common_args(parser)
    args = parser.parse_args()

    try:
        prereqs = check_prerequisites(require_real=args.require_real)
        version_id = args.version_id or prereqs["published_version_id"]

        # Task 9 — an unknown SID fails BEFORE any LLM call.
        advisors = {a["advisor_sid"]: a
                    for a in api_get("/api/advisors").get("advisors") or []}
        if args.advisor not in advisors:
            sample = ", ".join(sorted(advisors)[:5])
            raise GenError(f"unknown advisor SID '{args.advisor}' — no LLM call "
                           f"was made. Known SIDs include: {sample}, … "
                           f"(GET /api/advisors lists all {len(advisors)})")
        name = advisors[args.advisor].get("advisor_name") or "?"

        targets = [{"key": f"advisor|{args.advisor}|{args.from_month}|"
                           f"{args.to_month}|{version_id}",
                    "label": f"{args.advisor} ({name})",
                    "advisor": args.advisor,
                    "from": args.from_month, "to": args.to_month}]
        confirm_or_exit(
            f"1 advisor run: {args.advisor} ({name}) "
            f"{args.from_month} -> {args.to_month} on {version_id}\n"
            + cost_projection(1), args.yes)
        return run_targets(f"advisor_{args.advisor}", targets, args, version_id)
    except GenError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

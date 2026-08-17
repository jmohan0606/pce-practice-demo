#!/usr/bin/env python3
"""Round 4 task 10 — thin dispatcher over the three generation scripts.

    python3 scripts/generate_insights.py practice  --all-transitions
    python3 scripts/generate_insights.py topbottom --from 202604 --to 202605
    python3 scripts/generate_insights.py advisor   --advisor V000014 --from 202604 --to 202605

Pure delegation: the subcommand's remaining arguments pass through verbatim to
the standalone script (which stays independently runnable — this wrapper adds
one entry point, no behaviour).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = {
    "practice": "generate_practice_insights.py",
    "topbottom": "generate_topbottom_insights.py",
    "advisor": "generate_advisor_insights.py",
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") \
            or sys.argv[1] not in SCRIPTS:
        print(__doc__.strip())
        print(f"\nsubcommands: {' / '.join(SCRIPTS)}")
        return 0 if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help") else 2
    script = Path(__file__).resolve().parent / SCRIPTS[sys.argv[1]]
    return subprocess.call([sys.executable, str(script), *sys.argv[2:]])


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Round 8 — the direct-store-read guard (docs/STORE_READ_AUDIT.md).

Every module outside app/graph/ must read graph data through the tiered
client (catalog queries / named queries), never the foundation store directly:
a direct read silently serves MOCK rows in real mode while the dashboard shows
TigerGraph data (the evaluator bug, found in the client environment).

This script scans app/ (excluding app/graph/) for:
  - imports of get_foundation_store / FoundationGraphStore
  - calls of all_vertices( / .vertex(

and FAILS when any module exceeds its recorded baseline — the audited debt,
which may only SHRINK. A new read in any module, or any read in a new module,
fails naming the file and line. When the baseline is empty this script is the
strict guard: zero direct reads outside app/graph/.

Fixing a module? Delete (or lower) its baseline entry so the ratchet holds.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The audited baseline (docs/STORE_READ_AUDIT.md) — flagged-line counts per
# module at audit time. app/rules/evaluator.py is already fixed (absent).
BASELINE: dict[str, int] = {
    "app/api/routers/advisor.py": 10,
    "app/api/routers/insights.py": 16,
    "app/api/routers/nnm.py": 2,
    "app/chat/agent.py": 4,
    "app/export/providers.py": 4,
    "app/insights/describe.py": 9,
    "app/insights/exceptions.py": 7,
    "app/insights/service.py": 2,
    "app/rules/compiler.py": 4,
    "app/rules/service.py": 4,
}

# Reads and imports only — a docstring MENTIONING the class name is not a read.
PATTERNS = (
    re.compile(r"get_foundation_store"),
    re.compile(r"^\s*(from|import)\s.*FoundationGraphStore"),
    re.compile(r"\ball_vertices\("),
    re.compile(r"\.vertex\("),
)


def scan() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("app/graph/"):
            continue
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # commentary is not a read
            if any(p.search(line) for p in PATTERNS):
                found.setdefault(rel, []).append((no, stripped[:100]))
    return found


def main() -> int:
    found = scan()
    failures: list[str] = []
    for module, hits in sorted(found.items()):
        allowed = BASELINE.get(module, 0)
        if len(hits) > allowed:
            lines = "\n".join(f"      {module}:{no}  {text}" for no, text in hits)
            failures.append(
                f"  {module}: {len(hits)} direct-store line(s), baseline {allowed}\n{lines}")
    shrunk = [m for m in BASELINE
              if len(found.get(m, [])) < BASELINE[m]]
    gone = [m for m in BASELINE if m not in found]
    total = sum(len(h) for h in found.values())
    if failures:
        print("FAIL  direct foundation-store reads outside app/graph/ grew "
              "beyond the audited baseline — read through the tiered client "
              "(catalog queries) instead:\n" + "\n".join(failures))
        return 1
    print(f"PASS  direct-store-read ratchet: {total} flagged line(s) across "
          f"{len(found)} module(s), all within the audited baseline "
          f"({sum(BASELINE.values())} lines / {len(BASELINE)} modules; "
          f"app/rules/evaluator.py fixed)")
    if shrunk or gone:
        print(f"      baseline can tighten: fully clean={sorted(gone)}, "
              f"shrunk={sorted(m for m in shrunk if m not in gone)} — "
              f"lower/remove their entries in scripts/check_store_reads.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

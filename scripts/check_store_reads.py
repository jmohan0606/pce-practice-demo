#!/usr/bin/env python3
"""Round 8/9 — the direct-store-read guard (docs/STORE_READ_AUDIT.md).

Every module outside app/graph/ must read graph data through the tiered
client (catalog queries / named queries), never the foundation store directly:
a direct read silently serves MOCK rows in real mode while the dashboard shows
TigerGraph data (the evaluator bug, found in the client environment).

This script scans app/ (excluding app/graph/) for:
  - imports of get_foundation_store / FoundationGraphStore
  - calls of all_vertices( / .vertex(
  - Round 9 task 7 — the previously-open evasions: the tiered client's
    ``.store`` back-door property, the store's other read methods
    (out / inbound / out_ids / in_ids), and store-receiver .load( /
    .statistics( (receiver-narrowed so json.load / SQLite persistence loads /
    tiered-client statistics stay legal)

and FAILS when any module exceeds its recorded baseline — the audited debt,
which may only SHRINK. A new read in any module, or any read in a new module,
fails naming the file and line. The baseline is empty since Round 9 converted
every audited site, so this script IS the strict guard: zero direct reads
outside app/graph/.

Round 9 task 7 — the ratchet SELF-TIGHTENS: when a module comes in under its
baseline, this script rewrites its own BASELINE dict with the lower count, so
the ceiling only ever moves down (a module can never swap N reads for N
different ones under a stale ceiling).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The audited baseline (docs/STORE_READ_AUDIT.md) — flagged-line counts per
# module. EMPTY since Round 9 converted all audited sites; the guard is strict.
# Maintained by the script itself: an under-baseline run writes the lower
# count back (the ratchet only tightens).
BASELINE: dict[str, int] = {}

# Reads and imports only — a docstring MENTIONING the class name is not a read.
PATTERNS = (
    re.compile(r"get_foundation_store"),
    re.compile(r"^\s*(from|import)\s.*FoundationGraphStore"),
    re.compile(r"\ball_vertices\("),
    re.compile(r"\.vertex\("),
    # Round 9 task 7 — the remaining FoundationGraphStore read surface
    re.compile(r"\.out\("),
    re.compile(r"\.inbound\("),
    re.compile(r"\bout_ids\("),
    re.compile(r"\bin_ids\("),
    # receiver-narrowed: store.load( / fstore.statistics( are reads;
    # json.load( / self._persist.load( / graph_client.statistics( are not.
    re.compile(r"\b\w*store\.(load|statistics)\("),
)

# ``get_graph_client().store`` (the tiered client's mock-tier back-door) —
# checked on a string-literal-stripped copy of the line, and never on import
# lines, so ``from app.rules.store import …`` and logger names like
# "app.chat.store" are not false positives.
STORE_ATTR = re.compile(r"\.store\b")
IMPORT_LINE = re.compile(r"^\s*(from|import)\s")
STRING_LITERAL = re.compile(r"(\"[^\"]*\"|'[^']*')")


def _flagged(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("#"):
        return False  # commentary is not a read
    if any(p.search(line) for p in PATTERNS):
        return True
    if not IMPORT_LINE.match(line) \
            and STORE_ATTR.search(STRING_LITERAL.sub("''", line)):
        return True
    return False


def scan() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("app/graph/"):
            continue
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _flagged(line):
                found.setdefault(rel, []).append((no, line.strip()[:100]))
    return found


def _write_back(new_baseline: dict[str, int]) -> None:
    """Self-tighten: persist the lowered baseline into this file's own source."""
    me = Path(__file__)
    src = me.read_text(encoding="utf-8")
    # the marker is concatenated so this function's own source never matches
    # the substitution pattern below.
    marker = "BASELINE: dict[str, int] = "
    if new_baseline:
        body = "\n".join(f'    "{m}": {n},' for m, n in sorted(new_baseline.items()))
        block = marker + "{\n" + body + "\n}"
    else:
        block = marker + "{}"
    new_src, count = re.subn(
        re.escape(marker) + r"\{[^}]*\}", block.replace("\\", "\\\\"), src, count=1)
    if count == 1 and new_src != src:
        me.write_text(new_src, encoding="utf-8")


def main() -> int:
    found = scan()
    failures: list[str] = []
    for module, hits in sorted(found.items()):
        allowed = BASELINE.get(module, 0)
        if len(hits) > allowed:
            lines = "\n".join(f"      {module}:{no}  {text}" for no, text in hits)
            failures.append(
                f"  {module}: {len(hits)} direct-store line(s), baseline {allowed}\n{lines}")
    if failures:
        print("FAIL  direct foundation-store reads outside app/graph/ grew "
              "beyond the audited baseline — read through the tiered client "
              "(catalog queries) instead:\n" + "\n".join(failures))
        return 1
    total = sum(len(h) for h in found.values())
    tightened = {m: len(found.get(m, [])) for m in BASELINE
                 if len(found.get(m, [])) < BASELINE[m]}
    if tightened:
        new_baseline = {m: len(found.get(m, [])) for m in BASELINE}
        new_baseline = {m: n for m, n in new_baseline.items() if n > 0}
        _write_back(new_baseline)
        print(f"      ratchet tightened: {sorted(tightened)} written back "
              f"(baseline only moves down)")
    if BASELINE or total:
        print(f"PASS  direct-store-read ratchet: {total} flagged line(s) "
              f"within the recorded baseline "
              f"({sum(BASELINE.values())} lines / {len(BASELINE)} modules)")
    else:
        print("PASS  direct-store-read guard (STRICT): zero direct "
              "foundation-store reads outside app/graph/ — every read goes "
              "through the tiered client")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Round 4 (operator fix) — unit test of the reporter's numeric gate.

The seven cases the operator specified after finding the percentage hole:
_is_verified_combination accepted a percent token matching ANY ratio of ANY
two headline figures (36 ratios from 6 figures → ~1.6% of all percentage
values auto-accepted; an invented 87.3% passed as 48,007/54,978). A
percentage now needs BOTH its figures named in the same sentence or bullet.

Run: python3 scripts/check_numeric_gate.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.insights_reporter import verify_numbers  # noqa: E402

# The operator's reproduction set: headline figures come from finding
# impact_amts + the transition totals.
FINDINGS = [
    {"impact_amt": 37334.0, "evidence_rows": [], "summary": "", "title": ""},
    {"impact_amt": 48007.0, "evidence_rows": [], "summary": "", "title": ""},
    {"impact_amt": 54978.0, "evidence_rows": [], "summary": "", "title": ""},
]
TRANSITION = {"from_amt": 856000.0, "to_amt": 890165.52, "change_amt": 34165.52}

RESULTS: list[tuple[bool, str]] = []


def check(number: int, title: str, ok: bool, detail: str) -> None:
    RESULTS.append((ok, title))
    print(f"{'PASS' if ok else 'FAIL'}  NG-{number}. {title} — {detail}")


def main() -> int:
    # ---- accept 1: sum of two headline figures
    bad = verify_numbers("Together they contributed $85,341.", [], FINDINGS, TRANSITION)
    check(1, "ACCEPT a sum of two headline figures (37,334 + 48,007 = 85,341)",
          bad == [], f"rejected={bad}")

    # ---- accept 2: whole-dollar rounding of an allowed figure
    bad = verify_numbers("Revenue rose $34,166 in May.", [], FINDINGS, TRANSITION)
    check(2, "ACCEPT a whole-dollar rounding (34,166 for 34,165.52)",
          bad == [], f"rejected={bad}")

    # ---- accept 3: difference of two headline figures
    bad = verify_numbers("The gap between them is $17,644.", [], FINDINGS, TRANSITION)
    check(3, "ACCEPT a difference of two headline figures (54,978 − 37,334 = 17,644)",
          bad == [], f"rejected={bad}")

    # ---- accept 4: a percentage whose BOTH figures are named in the sentence
    bad = verify_numbers(
        "New billing of $48,007 replaced 87.3% of the $54,978 the book lost.",
        [], FINDINGS, TRANSITION)
    check(4, "ACCEPT a percentage with numerator AND denominator named in the "
             "same sentence (48,007 of 54,978 → 87.3%)",
          bad == [], f"rejected={bad}")

    # ---- reject 5: an invented figure
    bad = verify_numbers("A mystery $30,363 appeared.", [], FINDINGS, TRANSITION)
    check(5, "REJECT an invented figure (30,363)",
          bad == [30363.0], f"rejected={bad}")

    # ---- reject 6: an invented round number
    bad = verify_numbers("Roughly $50,000 of it was structural.", [], FINDINGS, TRANSITION)
    check(6, "REJECT an invented round number (50,000)",
          bad == [50000.0], f"rejected={bad}")

    # ---- reject 7: a three-figure sum
    three = 37334.0 + 48007.0 + 54978.0  # 140,319
    bad = verify_numbers(f"All three drivers total ${three:,.0f}.", [], FINDINGS, TRANSITION)
    check(7, "REJECT a three-figure sum (37,334 + 48,007 + 54,978 = 140,319)",
          bad == [three], f"rejected={bad}")

    # ---- reject 8: THE HOLE — 87.3% with neither of its figures named nearby
    bad = verify_numbers(
        "Retention held at 87.3% across the book.", [], FINDINGS, TRANSITION)
    check(8, "REJECT the operator's reproduction — 87.3% coincidentally equals "
             "48,007/54,978 but NEITHER figure is named in the sentence",
          bad == [87.3], f"rejected={bad}")

    # ---- and the scoping is per sentence: naming the figures in a DIFFERENT
    #      sentence must not launder the percentage
    bad = verify_numbers(
        "New billing was $48,007 against $54,978 lost. Retention held at 87.3%.",
        [], FINDINGS, TRANSITION)
    check(9, "REJECT 87.3% when its figures are named only in a DIFFERENT "
             "sentence (no cross-sentence laundering)",
          bad == [87.3], f"rejected={bad}")

    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Generate a small comp-plan-style test PDF with a REAL gridded table
(reportlab), for the B2 definition-of-done checks. Reused by
scripts/verify_round_b.py.

Usage:  python3 scripts/make_test_pdf.py [output_path]
Default output: data/uploads/test_comp_plan.pdf

Contents (deterministic):
  page 1: title, "1 Overview" + prose, "2 Payout Grid" + a 5-row rate TABLE
  page 2: "3 Adjustments" / "3.2 Discount Sharing" + prose long enough to chunk
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]

# The exact table rows — verify_round_b asserts the whole table survives in ONE chunk.
GRID_TABLE = [
    ["Tier", "Trailing 12-Month Revenue", "Payout Rate", "Bonus Rate"],
    ["1", "$0 - $250,000", "32%", "0.0%"],
    ["2", "$250,001 - $500,000", "36%", "0.5%"],
    ["3", "$500,001 - $1,000,000", "40%", "1.0%"],
    ["4", "Over $1,000,000", "44%", "1.5%"],
]

DISCOUNT_PROSE = (
    "When a client pays more than 10 percent below the standard fee schedule, the advisor "
    "shares in the discount. The payout grid moves down one point for every full percentage "
    "point of reduction beyond the 10 percent threshold, to a maximum reduction of ten grid "
    "points in any single month. "
)


def build_pdf(output_path: Path) -> Path:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13)
    body = styles["BodyText"]

    table = Table(GRID_TABLE, colWidths=[0.7 * inch, 2.4 * inch, 1.2 * inch, 1.2 * inch])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))

    story = [
        Paragraph("ADVISOR COMPENSATION PLAN 2026", h1),
        Spacer(1, 10),
        Paragraph("1 Overview", h1),
        Paragraph(
            "This plan document describes how advisor compensation is calculated for the 2026 "
            "plan year. Credited revenue is aggregated monthly per advisor and mapped to the "
            "payout grid below. Recurring and non-recurring revenue are treated identically for "
            "grid placement purposes.", body),
        Paragraph("2 Payout Grid", h1),
        Paragraph("The applicable payout rate is determined by trailing 12-month revenue:", body),
        table,
        PageBreak(),
        Paragraph("3 Adjustments", h1),
        Paragraph("3.2 Discount Sharing", h2),
        Paragraph(DISCOUNT_PROSE * 4, body),
        Paragraph(
            "Worked example (illustrative only — the standard managed fee schedule is 145 "
            "basis points): assume a schedule rate of 115 basis points and an actual fee of 100 "
            "basis points; the reduction is 13 percent, so the grid moves down 3 points for the "
            "affected accounts in that month.", body),
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output_path), pagesize=LETTER).build(story)
    return output_path


def main() -> None:
    default = APP_ROOT / "data" / "uploads" / "test_comp_plan.pdf"
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    path = build_pdf(output)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

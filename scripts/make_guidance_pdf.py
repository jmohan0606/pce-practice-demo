"""Generate a small practice-management GUIDANCE PDF (reportlab) — the Coach's
retrieval source (Round A2B 6.7). Idiom copied from scripts/make_test_pdf.py.

Usage:  python3 scripts/make_guidance_pdf.py [output_path]
Default output: docs/sample/practice_guidance_2026_sample.pdf

Contents (deterministic, ~2 pages): four titled guidance paragraphs —
discount discipline, household consolidation, book diversification,
referral follow-up.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]

SECTIONS = [
    ("1 Discount Discipline", (
        "Fee discounts compound silently. An advisor whose average reduction from the standard "
        "schedule exceeds the practice norm should review each discounted relationship annually. "
        "Discounts granted to win a household rarely get revisited once the household is settled, "
        "and a book that discounts broadly ranks near the top on discount rate while ranking "
        "mid-pack on revenue. Recommended practice: review every account priced below the "
        "standard schedule at the annual client review, and require a written rationale for any "
        "discount that continues into a new plan year. Where the practice average discount is "
        "known, compare the advisor's blended reduction to that average before agreeing new "
        "concessions."
    )),
    ("2 Household Consolidation", (
        "Small households near a crediting threshold are the most common source of non-credited "
        "revenue. Consolidating related accounts into one household relationship moves balances "
        "over the threshold and turns non-credited trades into credited ones. Recommended "
        "practice: when a client family holds accounts across several household identifiers, "
        "initiate a householding review before year end; the accounts most worth reviewing are "
        "those within reach of the threshold, where a single consolidation changes the crediting "
        "outcome. Consolidation also simplifies fee schedules and reduces the count of "
        "below-minimum relationships an advisor must justify."
    )),
    ("3 Book Diversification", (
        "A book concentrated in one product family is exposed to a single repricing event. "
        "Advisors whose revenue depends on one product group for more than half of credited "
        "revenue should identify the next two product conversations for each of their top "
        "households. Recommended practice: track the share of credited revenue by product group "
        "each month; where one group's share grows for three consecutive months, schedule a "
        "portfolio review with the largest households in that group before the concentration "
        "becomes structural. Diversified books retain more accounts through market stress."
    )),
    ("4 Referral Follow-Up", (
        "Referral opportunities decay quickly: a referred prospect contacted within one week "
        "converts at a materially higher rate than one contacted after a month. Recommended "
        "practice: every open opportunity in the pipeline should carry a next-contact date, and "
        "pending opportunities older than thirty days should be reviewed at the weekly practice "
        "meeting. A lost opportunity should record the reason it was lost — pricing, timing, or "
        "competitor — because the pattern across lost opportunities is the practice's best "
        "signal of where its proposition is weakest. Won opportunities warrant a thank-you to "
        "the referring client within the same week."
    )),
]


def build_pdf(output_path: Path) -> Path:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13)
    body = styles["BodyText"]

    story = [
        Paragraph("PRACTICE MANAGEMENT GUIDANCE 2026", h1),
        Spacer(1, 10),
        Paragraph(
            "This guidance document collects recommended practice for advisor coaching "
            "conversations. It is guidance, not plan policy: nothing here changes how revenue "
            "is credited. Each section states the recommended practice and the situation it "
            "addresses.", body),
    ]
    for i, (title, prose) in enumerate(SECTIONS):
        story.append(Paragraph(title, h2))
        story.append(Paragraph(prose, body))
        if i == 1:
            story.append(PageBreak())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output_path), pagesize=LETTER).build(story)
    return output_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        APP_ROOT / "docs" / "sample" / "practice_guidance_2026_sample.pdf")
    print(build_pdf(target))

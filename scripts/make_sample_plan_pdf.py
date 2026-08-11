"""Round C task 3 — generate docs/sample/comp_plan_2026_sample.pdf.

A realistic advisor compensation plan written as PROSE AND TABLES — not a list
of rules. The Rule Extractor has to FIND the provisions. Required content
(task 3 table): the 10% fee-discount sharing rule as a rate table plus prose,
the 115→100 bps worked example, rounding to the nearest whole percent, the
$4MM net-new-money award, the six-month departed-advisor suspension, inherited
transferred accounts, mid-period account openings, a referral cap whose
threshold is deliberately NEVER stated (must extract as NEEDS_INPUT), and a
rate table of at least 15 rows (table-integrity chunking on real content).

Usage: python3 scripts/make_sample_plan_pdf.py [output_path]
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = APP_ROOT / "docs" / "sample" / "comp_plan_2026_sample.pdf"

# ≥15 rows — exercises table-integrity chunking on real content.
PAYOUT_SCHEDULE = [
    ["Band", "Trailing 12-Month Credited Revenue", "Core Payout", "Deferred Award", "Team Uplift"],
    ["A1", "$0 – $175,000", "30.0%", "0.00%", "0.0%"],
    ["A2", "$175,001 – $250,000", "31.5%", "0.00%", "0.0%"],
    ["A3", "$250,001 – $325,000", "33.0%", "0.25%", "0.0%"],
    ["A4", "$325,001 – $400,000", "34.5%", "0.25%", "0.5%"],
    ["B1", "$400,001 – $500,000", "36.0%", "0.50%", "0.5%"],
    ["B2", "$500,001 – $625,000", "37.5%", "0.50%", "0.5%"],
    ["B3", "$625,001 – $750,000", "39.0%", "0.75%", "1.0%"],
    ["B4", "$750,001 – $900,000", "40.5%", "0.75%", "1.0%"],
    ["C1", "$900,001 – $1,100,000", "42.0%", "1.00%", "1.0%"],
    ["C2", "$1,100,001 – $1,350,000", "43.0%", "1.00%", "1.5%"],
    ["C3", "$1,350,001 – $1,650,000", "44.0%", "1.25%", "1.5%"],
    ["C4", "$1,650,001 – $2,000,000", "45.0%", "1.25%", "1.5%"],
    ["D1", "$2,000,001 – $2,500,000", "46.0%", "1.50%", "2.0%"],
    ["D2", "$2,500,001 – $3,250,000", "47.0%", "1.50%", "2.0%"],
    ["D3", "$3,250,001 – $4,000,000", "48.0%", "1.75%", "2.0%"],
    ["D4", "Over $4,000,000", "49.0%", "2.00%", "2.5%"],
]

# The discount-sharing grid movement as a RATE TABLE (plus the prose around it).
DISCOUNT_GRID = [
    ["Effective Fee Reduction", "Grid Point Movement"],
    ["10% or less", "No movement"],
    ["11%", "Down 1 point"],
    ["12%", "Down 2 points"],
    ["13%", "Down 3 points"],
    ["15%", "Down 5 points"],
    ["18%", "Down 8 points"],
    ["20% or more", "Down 10 points (floor)"],
]


def build_pdf(output_path: Path = DEFAULT_OUT) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceAfter=6)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12.5, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10.5, leading=14)

    def table_of(data, widths):
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE4EE")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    p = lambda text: Paragraph(text, body)  # noqa: E731
    story = [
        Paragraph("CWM PRIVATE CLIENT GROUP", h1),
        Paragraph("Financial Advisor Compensation Plan — Plan Year 2026", h2),
        Spacer(1, 8),
        Paragraph("1  Purpose and Scope", h1),
        p("This plan describes how credited revenue is measured and how the advisor payout "
          "grid responds to client pricing decisions, asset movement, and practice events "
          "during the 2026 plan year. It applies to all producing advisors in the Private "
          "Client Group, whether operating individually or under a team agreement. Unless a "
          "provision states otherwise, measurements are made monthly on credited revenue as "
          "recorded in the firm's revenue system, and grid placement is re-evaluated at the "
          "close of each production month."),
        p("Nothing in this plan creates an entitlement to a particular payout band. Where "
          "this plan is silent, the 2025 plan's administrative interpretations continue to "
          "apply until superseded in writing by Compensation Committee action."),
        Spacer(1, 6),

        Paragraph("2  Payout Schedule", h1),
        p("An advisor's core payout rate is determined by the band containing their trailing "
          "twelve-month credited revenue. The deferred award accrues quarterly and vests per "
          "the firm's deferral policy; the team uplift applies only to advisors on an active "
          "team agreement with an executed revenue-share schedule."),
        table_of(PAYOUT_SCHEDULE, [0.6 * inch, 2.5 * inch, 1.1 * inch, 1.2 * inch, 1.0 * inch]),
        p("Band placement is recalculated monthly. A month in which fewer trading days occur "
          "than in the preceding month — for example a mid-month data cutoff or an exchange "
          "holiday cluster — will show lower recurring revenue for reasons unrelated to the "
          "advisor's book, and band placement is not adjusted downward on that basis alone."),
        PageBreak(),

        Paragraph("3  Client Fee Discounts and Grid Sharing", h1),
        Paragraph("3.1  The Sharing Threshold", h2),
        p("The firm expects most client relationships to price at or near the standard fee "
          "schedule. When a client's effective fee falls more than ten percent (10%) below "
          "the standard schedule for a managed account, the advisor shares in that discount "
          "through grid movement: the payout grid moves down one point for each full "
          "percentage point of reduction beyond the 10% threshold. The grid never moves "
          "more than ten points for this reason in any single month — deeper discounts are "
          "absorbed by the firm once the ten-point floor is reached."),
        p("Discount sharing applies to managed accounts only. It applies only where the "
          "pricing decision was made on or after 1 April 2026; discounts in force before "
          "that date are excluded from sharing for as long as they remain unchanged. "
          "Re-papering an existing discount without changing its economics does not create "
          "a new pricing decision."),
        table_of(DISCOUNT_GRID, [2.6 * inch, 2.6 * inch]),
        Paragraph("3.2  Worked Example", h2),
        p("A managed account carries a standard schedule rate of 115 bps. The advisor "
          "agrees with the client on an effective rate of 100 bps in May 2026. The "
          "reduction is (115 − 100) / 115 = 13%. That is 3 full points beyond the 10% "
          "threshold, so the advisor's grid moves down 3 points for that month's "
          "production on the account."),
        Paragraph("3.3  Rounding", h2),
        p("The effective reduction percentage is rounded to the nearest whole percent "
          "before the grid movement is applied. A computed reduction of 14.4% is treated "
          "as 14%, moving the grid down 4 points; a computed reduction of 14.50% rounds "
          "up and is treated as 15%, moving the grid down 5 points."),
        Paragraph("3.4  Departure of the Discounting Advisor", h2),
        p("When the advisor who originally set a client discount leaves the firm, discount "
          "sharing on the affected accounts is suspended for six months from the departure "
          "date, then resumes automatically for whichever advisor then serves the account. "
          "The suspension recognises that the receiving advisor did not make the original "
          "pricing decision and needs a transition period to revisit it with the client."),
        PageBreak(),

        Paragraph("4  Asset Movement and the Book", h1),
        Paragraph("4.1  Account Transfers Between Advisors", h2),
        p("An account reassigned from one advisor to another — whether through a book "
          "purchase, a team restructuring, or a management-directed move — is a transfer, "
          "not a lost account, and must never be counted against the sending advisor as an "
          "account loss. For the receiving advisor, an inherited account that carries a "
          "client fee discount above the sharing threshold continues to count toward "
          "discount sharing: the discount follows the account, not the advisor who set "
          "it. The six-month suspension in Section 3.4 applies only to departures from "
          "the firm, not to internal book moves."),
        Paragraph("4.2  New Accounts Opened Mid-Period", h2),
        p("An account opened during a production month is treated as new for the month in "
          "which its first credited revenue appears. An account opened on the 20th of a "
          "month whose first trade settles in the following month is therefore a new "
          "account of the following month. Opening paperwork alone does not create a new "
          "account for compensation purposes; credited revenue does."),
        Paragraph("4.3  Lost Accounts", h2),
        p("An account whose balance falls to zero and which produced credited revenue in "
          "the prior month is a lost account of the current month, unless a transfer "
          "record exists for it — a transferred account is governed by Section 4.1 and is "
          "excluded from the lost-account count."),
        Spacer(1, 6),

        Paragraph("5  Net New Money Award", h1),
        p("An advisor qualifies for the net new money award once total net new money for "
          "the plan year reaches four million dollars ($4,000,000). Once qualified, the "
          "award equals the plan-year net new money multiplied by the award rate and by "
          "the advisor's effective grid rate at the time of calculation. Net new money is "
          "measured as total inflows less total outflows across all flow products, before "
          "market movement. Flows attributable to a departed advisor's book in the six "
          "months following the departure are excluded from the receiving advisor's net "
          "new money for award purposes."),
        Spacer(1, 6),

        Paragraph("6  Referral Programs", h1),
        p("Referral-driven flows participate in the same credited-revenue measurement as "
          "all other business, subject to program terms. Note that a cap applies to "
          "referral-driven flows counted toward the net new money award in any plan year; "
          "the cap amount is established annually by the Compensation Committee and "
          "communicated under separate cover. Referral flows above the cap continue to "
          "credit revenue normally but do not count toward award qualification."),
        Spacer(1, 6),

        Paragraph("7  Administration", h1),
        p("The Compensation Committee administers this plan and resolves interpretive "
          "questions. Grid movements under Section 3 are recorded on each affected "
          "transaction as a grid reduction; advisors should review recorded reductions "
          "monthly and raise discrepancies within sixty days. The firm may amend this "
          "plan prospectively at any time with thirty days' notice."),
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output_path), pagesize=LETTER,
                      title="CWM FA Compensation Plan 2026").build(story)
    return output_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    print(build_pdf(out))

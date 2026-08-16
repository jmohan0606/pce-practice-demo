"""Round F2 — GENERIC content-file-to-PDF renderer for sample plan documents.

This script deliberately contains NO plan content: no rates, tables,
thresholds or prose. Everything it renders comes from a content .md file
(default docs/sample/cwm_pca_plan_2026_content.md) so that plan-document
values never live in a Python file (Round F2 check 13; DECISIONS.md
2026-08-16 "Plan tables enter ONLY via document files").

Content format (kept intentionally tiny):
  <!-- ... -->   HTML comment (single- or multi-line) — ignored
  <!-PAGE->      hard page break
  # Heading      section heading
  | a | b | c |  table row (consecutive rows form one table; first row = header)
  - text         bullet
  plain line     paragraph text (blank line separates paragraphs)

Usage: python3 scripts/render_plan_pdf.py [content.md] [output.pdf]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTENT = APP_ROOT / "docs" / "sample" / "cwm_pca_plan_2026_content.md"
DEFAULT_OUT = APP_ROOT / "docs" / "sample" / "cwm_pca_plan_2026.pdf"

NAVY = colors.HexColor("#1b2a4a")

TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15,
                       leading=19, spaceAfter=10, textColor=NAVY)
HEAD = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=12,
                      leading=15, spaceBefore=12, spaceAfter=6, textColor=NAVY)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14,
                      spaceAfter=6)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=16, bulletIndent=6)


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def build_flowables(content: str) -> list:
    flow: list = []
    first_heading = True
    lines = _strip_comments(content).splitlines()
    table_rows: list[list[str]] = []
    para: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            flow.append(Paragraph(" ".join(para), BODY))
            para = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        width = (LETTER[0] - 2 * inch) / max(len(r) for r in table_rows)
        t = Table(table_rows, colWidths=[width] * len(table_rows[0]))
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c0cf")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f2f4f8")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 8))
        table_rows = []

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == "<!-PAGE->":
            flush_para(); flush_table()
            flow.append(PageBreak())
        elif stripped.startswith("|") and stripped.endswith("|"):
            flush_para()
            table_rows.append([c.strip() for c in stripped.strip("|").split("|")])
        elif stripped.startswith("# "):
            flush_para(); flush_table()
            style = TITLE if first_heading else HEAD
            first_heading = False
            flow.append(Paragraph(stripped[2:], style))
        elif stripped.startswith("- "):
            flush_para(); flush_table()
            flow.append(Paragraph(stripped[2:], BULLET, bulletText="•"))
        elif not stripped:
            flush_para(); flush_table()
        else:
            flush_table()
            para.append(stripped)
    flush_para(); flush_table()
    return flow


def render(content_path: Path, out_path: Path) -> Path:
    doc = BaseDocTemplate(str(out_path), pagesize=LETTER,
                          leftMargin=inch, rightMargin=inch,
                          topMargin=0.9 * inch, bottomMargin=0.9 * inch)

    def number_page(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawCentredString(LETTER[0] / 2, 0.55 * inch,
                                 f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame],
                                       onPage=number_page)])
    doc.build(build_flowables(content_path.read_text()))
    return out_path


if __name__ == "__main__":
    content = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONTENT
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    render(content, out)
    print(f"rendered {content} -> {out}")

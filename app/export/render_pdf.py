"""PDF renderer (reportlab platypus) — navy header, colour-coded signed
columns, parenthesised negatives, definitions footnote, traceability footer.
Header names the transition and view (payload subtitle)."""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.export.payload import (NAVY, NEGATIVE_RED, NO_DATA_TEXT,
                                POSITIVE_GREEN, fmt_display, is_negative)

_NAVY = colors.HexColor(NAVY)
_POS = colors.HexColor(POSITIVE_GREEN)
_NEG = colors.HexColor(NEGATIVE_RED)
_SLATE = colors.HexColor("#5A6B7D")
_TOT_BG = colors.HexColor("#EDF1F6")


def render_pdf(payload: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=payload["title"])
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("XTitle", parent=styles["Title"],
                                 textColor=_NAVY, fontSize=16, spaceAfter=2)
    sub_style = ParagraphStyle("XSub", parent=styles["Normal"],
                               textColor=_SLATE, fontSize=10, spaceAfter=8)
    note_style = ParagraphStyle("XNote", parent=styles["Normal"],
                                textColor=_SLATE, fontSize=7.5, leading=9.5)
    cell_style = ParagraphStyle("XCell", parent=styles["Normal"], fontSize=8,
                                leading=10)

    story = [Paragraph(payload["title"], title_style),
             Paragraph(payload["subtitle"], sub_style)]
    for line in payload.get("preamble") or []:
        story.append(Paragraph(line, ParagraphStyle(
            "XPre", parent=styles["Normal"], fontSize=9, leading=12, spaceAfter=3)))
    if payload.get("preamble"):
        story.append(Spacer(1, 4 * mm))

    columns = payload["columns"]
    header = [Paragraph(f"<b>{c['label']}</b>", ParagraphStyle(
        "XHead", parent=cell_style, textColor=colors.white)) for c in columns]
    table_data: list[list] = [header]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C6D0DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F6F8FA")]),
    ]

    rows = payload["rows"]
    if not rows:
        table_data.append([Paragraph(NO_DATA_TEXT, cell_style)]
                          + [""] * (len(columns) - 1))
        style_cmds.append(("SPAN", (0, 1), (-1, 1)))
    else:
        body = list(rows)
        if payload.get("totals"):
            body.append({**payload["totals"], "_role": "total"})
        for r, row in enumerate(body, start=1):
            line = []
            for c, column in enumerate(columns):
                value = row.get(column["key"])
                text = fmt_display(value, column["type"])
                if column["type"] == "text":
                    line.append(Paragraph(text, cell_style))
                else:
                    line.append(text)
                    style_cmds.append(("ALIGN", (c, r), (c, r), "RIGHT"))
                    if column.get("signed") and value is not None:
                        style_cmds.append(("TEXTCOLOR", (c, r), (c, r),
                                           _NEG if is_negative(value) else _POS))
            if row.get("_role") in ("subtotal", "total"):
                style_cmds += [("BACKGROUND", (0, r), (-1, r), _TOT_BG),
                               ("FONTNAME", (0, r), (-1, r), "Helvetica-Bold"),
                               ("LINEABOVE", (0, r), (-1, r), 1.2, _NAVY)]
            table_data.append(line)

    style_cmds.append(("FONTSIZE", (0, 1), (-1, -1), 8))
    table = Table(table_data, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(style_cmds))
    story.append(table)

    story.append(Spacer(1, 5 * mm))
    if payload.get("footnotes"):
        story.append(Paragraph("<b>Definitions</b>", note_style))
        for note in payload["footnotes"]:
            story.append(Paragraph(note, note_style))
        story.append(Spacer(1, 2 * mm))
    footer = payload["footer"]
    story.append(Paragraph(
        f"Source: {footer['source']} · Generated: {footer['generated_at']} · "
        f"Rule set version: {footer['rule_set_version']}", note_style))

    doc.build(story)
    return buffer.getvalue()

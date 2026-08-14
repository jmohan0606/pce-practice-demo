"""XLSX renderer — RAW values with number formats (never pre-formatted
strings) so the client can pivot. Negatives show in parentheses via the
number format, not string mangling. Traceability footer on the sheet."""
from __future__ import annotations

import io

import xlsxwriter

from app.export.payload import NAVY, NEGATIVE_RED, NO_DATA_TEXT, POSITIVE_GREEN

_MONEY_FMT = "#,##0.00_);(#,##0.00)"
_INT_FMT = "#,##0_);(#,##0)"
_PCT_FMT = "0.00%_);(0.00%)"


def render_xlsx(payload: dict) -> bytes:
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {"in_memory": True})
    sheet = book.add_worksheet(payload["section"][:31])

    header_fmt = book.add_format({"bold": True, "font_color": "#FFFFFF",
                                  "bg_color": NAVY, "border": 1})
    title_fmt = book.add_format({"bold": True, "font_size": 14})
    total_fmt = {"bold": True, "top": 2}
    formats = {
        "text": book.add_format({}),
        "int": book.add_format({"num_format": _INT_FMT}),
        "money": book.add_format({"num_format": _MONEY_FMT}),
        "pct": book.add_format({"num_format": _PCT_FMT}),
    }
    total_formats = {
        kind: book.add_format({**total_fmt,
                               **({"num_format": fmt} if fmt else {})})
        for kind, fmt in (("text", None), ("int", _INT_FMT),
                          ("money", _MONEY_FMT), ("pct", _PCT_FMT))
    }
    # signed columns: colour by sign (parentheses already come from the format)
    pos_fmts = {k: book.add_format({"num_format": f, "font_color": POSITIVE_GREEN})
                for k, f in (("int", _INT_FMT), ("money", _MONEY_FMT), ("pct", _PCT_FMT))}
    neg_fmts = {k: book.add_format({"num_format": f, "font_color": NEGATIVE_RED})
                for k, f in (("int", _INT_FMT), ("money", _MONEY_FMT), ("pct", _PCT_FMT))}

    row_no = 0
    sheet.write(row_no, 0, payload["title"], title_fmt); row_no += 1
    sheet.write(row_no, 0, payload["subtitle"]); row_no += 1
    for line in payload.get("preamble") or []:
        sheet.write(row_no, 0, line); row_no += 1
    row_no += 1

    columns = payload["columns"]
    for c, column in enumerate(columns):
        sheet.write(row_no, c, column["label"], header_fmt)
        sheet.set_column(c, c, 14 if column["type"] != "text" else 24)
    row_no += 1

    def _write_cell(r: int, c: int, column: dict, value, *, total: bool = False) -> None:
        kind = column["type"]
        if value is None or value == "":
            sheet.write_blank(r, c, None, total_formats[kind] if total else formats[kind])
            return
        if kind == "text":
            sheet.write_string(r, c, str(value),
                               total_formats["text"] if total else formats["text"])
            return
        number = float(value)
        if kind == "pct":
            number = number / 100.0  # raw fraction + percent number format
        fmt = total_formats[kind] if total else formats[kind]
        if not total and column.get("signed"):
            fmt = (neg_fmts if number < 0 else pos_fmts)[kind]
        sheet.write_number(r, c, number, fmt)

    rows = payload["rows"]
    if not rows:
        sheet.write(row_no, 0, NO_DATA_TEXT); row_no += 1
    else:
        for row in rows:
            for c, column in enumerate(columns):
                _write_cell(row_no, c, column, row.get(column["key"]))
            row_no += 1
        if payload.get("totals"):
            for c, column in enumerate(columns):
                _write_cell(row_no, c, column, payload["totals"].get(column["key"]),
                            total=True)
            row_no += 1

    row_no += 1
    note_fmt = book.add_format({"font_color": "#5A6B7D", "italic": True})
    for note in payload.get("footnotes") or []:
        sheet.write(row_no, 0, note, note_fmt); row_no += 1
    footer = payload["footer"]
    sheet.write(row_no, 0, "source", note_fmt)
    sheet.write(row_no, 1, footer["source"], note_fmt); row_no += 1
    sheet.write(row_no, 0, "generated_at", note_fmt)
    sheet.write(row_no, 1, footer["generated_at"], note_fmt); row_no += 1
    sheet.write(row_no, 0, "rule_set_version", note_fmt)
    sheet.write(row_no, 1, footer["rule_set_version"], note_fmt)

    book.close()
    return buffer.getvalue()

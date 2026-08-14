"""CSV renderer — plain values, trailing metadata rows for traceability."""
from __future__ import annotations

import csv
import io

from app.export.payload import NO_DATA_TEXT


def render_csv(payload: dict) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([payload["title"]])
    writer.writerow([payload["subtitle"]])
    for line in payload.get("preamble") or []:
        writer.writerow([line])
    writer.writerow([])

    columns = payload["columns"]
    writer.writerow([c["label"] for c in columns])
    rows = payload["rows"]
    if not rows:
        writer.writerow([NO_DATA_TEXT])
    else:
        for row in rows:
            writer.writerow([row.get(c["key"], "") for c in columns])
        if payload.get("totals"):
            writer.writerow([payload["totals"].get(c["key"], "") for c in columns])

    writer.writerow([])
    for note in payload.get("footnotes") or []:
        writer.writerow([f"# {note}"])
    footer = payload["footer"]
    writer.writerow([f"# source: {footer['source']}"])
    writer.writerow([f"# generated_at: {footer['generated_at']}"])
    writer.writerow([f"# rule_set_version: {footer['rule_set_version']}"])
    return buffer.getvalue().encode("utf-8-sig")

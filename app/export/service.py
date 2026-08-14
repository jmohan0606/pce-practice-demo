"""Export service — payload from the provider registry, bytes from the
renderer registry. A new section touches providers.py only; a new format
touches this table only."""
from __future__ import annotations

from typing import Callable

from app.export.providers import ExportParamError, SECTIONS, build_payload
from app.export.render_csv import render_csv
from app.export.render_pdf import render_pdf
from app.export.render_pptx import render_pptx
from app.export.render_xlsx import render_xlsx

FORMATS = ("pdf", "pptx", "xlsx", "csv")

RENDERERS: dict[str, tuple[Callable[[dict], bytes], str]] = {
    "pdf": (render_pdf, "application/pdf"),
    "pptx": (render_pptx,
             "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "xlsx": (render_xlsx,
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "csv": (render_csv, "text/csv; charset=utf-8"),
}


def export_file(section: str, format_: str, params: dict) -> tuple[bytes, str, str]:
    """Returns (content bytes, media type, filename). The filename carries
    section + transition + view via the provider's filename_stem."""
    if format_ not in RENDERERS:
        raise ExportParamError(
            f"unknown format '{format_}' (expected {'|'.join(FORMATS)})")
    payload = build_payload(section, params)
    renderer, media_type = RENDERERS[format_]
    return renderer(payload), media_type, f"{payload['filename_stem']}.{format_}"


__all__ = ["FORMATS", "SECTIONS", "ExportParamError", "export_file"]

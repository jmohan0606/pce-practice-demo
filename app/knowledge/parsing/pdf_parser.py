"""PDF parsing via pdfplumber (Round B rework, spec B2.1).

Per-page text with coordinates AND extract_tables() — V1's pypdf flattened
tables into meaningless text streams; comp plans are mostly tables.

Heading detection (priority order, spec B2.1):
  1. Numbered pattern  ^\\d+(\\.\\d+)*\\s+\\S      -> level = dot count + 1
  2. Font size above the page's modal body size, on a short line (< 80 chars)
  3. ALL CAPS on a short line

Heading detection is heuristic; section_path is provenance, not logic.
What must never be wrong is page_no — every block carries the pdfplumber
1-based page number it was read from.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.knowledge.parsing.base import ParsedBlock, ParsedDocument, table_to_markdown

NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\s+\S")
MAX_HEADING_CHARS = 80
# A line must be this much larger than the modal body size to read as a heading.
FONT_SIZE_MARGIN = 0.5
# Vertical gap (in multiples of line height) that starts a new paragraph.
PARAGRAPH_GAP_FACTOR = 1.6


def _in_any_bbox(x: float, top: float, bboxes: list[tuple]) -> bool:
    return any(x0 <= x <= x1 and t0 <= top <= t1 for (x0, t0, x1, t1) in bboxes)


def _classify_line(text: str, size: float, modal_size: float) -> tuple[str, int]:
    """(block_type, heading_level) for one assembled line."""
    match = NUMBERED_HEADING.match(text)
    if match and len(text) <= MAX_HEADING_CHARS:
        return "heading", match.group(1).count(".") + 1
    if len(text) < MAX_HEADING_CHARS and size > modal_size + FONT_SIZE_MARGIN:
        # Larger jump above body size -> higher-level heading.
        return "heading", 1 if size >= modal_size * 1.25 else 2
    letters = [c for c in text if c.isalpha()]
    if letters and len(text) < MAX_HEADING_CHARS and all(c.isupper() for c in letters):
        return "heading", 1
    return "paragraph", 0


def parse_pdf(path: str | Path) -> ParsedDocument:
    import pdfplumber

    path = Path(path)
    blocks: list[ParsedBlock] = []
    order = 0
    with pdfplumber.open(str(path)) as pdf:
        page_count = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages, start=1):
            page_items: list[tuple[float, ParsedBlock]] = []  # (top, block)

            # --- tables first: their bboxes exclude table words from prose ---
            tables = page.find_tables()
            table_bboxes = [t.bbox for t in tables]
            for t in tables:
                rows = [r for r in t.extract() if any(c not in (None, "") for c in r)]
                markdown = table_to_markdown(rows)
                if markdown:
                    page_items.append((t.bbox[1], ParsedBlock(
                        block_type="table", text=markdown,
                        page_no=page_index, heading_level=0, order=0,
                    )))

            # --- prose: words outside table bboxes, assembled into lines ---
            words = page.extract_words(extra_attrs=["size"], use_text_flow=False)
            lines: dict[float, list[dict]] = {}
            for w in words:
                cx = (w["x0"] + w["x1"]) / 2
                cy = (w["top"] + w["bottom"]) / 2
                if _in_any_bbox(cx, cy, table_bboxes):
                    continue
                lines.setdefault(round(w["top"], 0), []).append(w)
            if lines:
                # Modal body font size for THIS page (weighted by word count).
                size_counts = Counter(
                    round(float(w.get("size") or 0), 1)
                    for ws in lines.values() for w in ws
                )
                modal_size = size_counts.most_common(1)[0][0] if size_counts else 0.0

                assembled = []  # (top, text, max_size, height)
                for top in sorted(lines):
                    ws = sorted(lines[top], key=lambda w: w["x0"])
                    text = " ".join(w["text"] for w in ws).strip()
                    if not text:
                        continue
                    max_size = max(float(w.get("size") or 0) for w in ws)
                    height = max(w["bottom"] - w["top"] for w in ws)
                    assembled.append((top, text, max_size, height))

                # Group consecutive lines into paragraph/heading blocks.
                para_lines: list[tuple[float, str]] = []

                def flush_paragraph():
                    if not para_lines:
                        return
                    top0 = para_lines[0][0]
                    text = " ".join(t for _, t in para_lines)
                    page_items.append((top0, ParsedBlock(
                        block_type="paragraph", text=text,
                        page_no=page_index, heading_level=0, order=0,
                    )))
                    para_lines.clear()

                prev_bottom: float | None = None
                for top, text, max_size, height in assembled:
                    block_type, level = _classify_line(text, max_size, modal_size)
                    if block_type == "heading":
                        flush_paragraph()
                        page_items.append((top, ParsedBlock(
                            block_type="heading", text=text,
                            page_no=page_index, heading_level=level, order=0,
                        )))
                    else:
                        if (para_lines and prev_bottom is not None
                                and top - prev_bottom > height * PARAGRAPH_GAP_FACTOR):
                            flush_paragraph()
                        para_lines.append((top, text))
                    prev_bottom = top + height
                flush_paragraph()

            # Interleave tables and prose by vertical position on the page.
            for top, block in sorted(page_items, key=lambda item: item[0]):
                block.order = order
                blocks.append(block)
                order += 1

    return ParsedDocument(source_name=path.name, page_count=page_count, blocks=blocks)

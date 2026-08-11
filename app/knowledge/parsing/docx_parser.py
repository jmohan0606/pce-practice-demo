"""DOCX parsing via python-docx (Round B rework, spec B2.1).

Paragraphs and tables in true document order (walking the body XML), with
Word's own paragraph styles supplying heading levels — no font heuristics
needed. DOCX has no fixed pagination (pages exist only at render time), so
page_no is 1 for every block: a constant is honest; a guess would be wrong.
"""

from __future__ import annotations

from pathlib import Path

from app.knowledge.parsing.base import ParsedBlock, ParsedDocument, table_to_markdown


def _heading_level(style_name: str) -> int:
    name = (style_name or "").strip().lower()
    if name == "title":
        return 1
    if name.startswith("heading"):
        try:
            return max(1, int(name.split()[-1]))
        except (ValueError, IndexError):
            return 1
    return 0


def parse_docx(path: str | Path) -> ParsedDocument:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    path = Path(path)
    document = Document(str(path))
    blocks: list[ParsedBlock] = []
    order = 0

    # iter_inner_content walks paragraphs and tables in document order.
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            level = _heading_level(getattr(item.style, "name", "") or "")
            style_name = (getattr(item.style, "name", "") or "").lower()
            if level > 0:
                block_type, heading_level = "heading", level
            elif "list" in style_name:
                block_type, heading_level = "list", 0
            else:
                block_type, heading_level = "paragraph", 0
            blocks.append(ParsedBlock(
                block_type=block_type, text=text, page_no=1,
                heading_level=heading_level, order=order,
            ))
            order += 1
        elif isinstance(item, Table):
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            rows = [r for r in rows if any(c.strip() for c in r)]
            markdown = table_to_markdown(rows)
            if markdown:
                blocks.append(ParsedBlock(
                    block_type="table", text=markdown, page_no=1,
                    heading_level=0, order=order,
                ))
                order += 1

    return ParsedDocument(source_name=path.name, page_count=1, blocks=blocks)

"""Format-dispatching document parsing (Round B rework, spec B2.1).

parse_document(path) -> ParsedDocument for .pdf (pdfplumber), .docx
(python-docx), .pptx (python-pptx) and plain-text formats (one paragraph block
per blank-line-separated chunk, page 1). No fallbacks between libraries — a
missing library is a loud ImportError, never a silent quality downgrade.
"""

from __future__ import annotations

from pathlib import Path

from app.knowledge.parsing.base import ParsedBlock, ParsedDocument, table_to_markdown

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md"}
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".pptx"} | SUPPORTED_TEXT_SUFFIXES


def _parse_text(path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    blocks: list[ParsedBlock] = []
    order = 0
    for part in raw.split("\n\n"):
        text = part.strip()
        if not text:
            continue
        blocks.append(ParsedBlock(
            block_type="paragraph", text=text, page_no=1, heading_level=0, order=order,
        ))
        order += 1
    return ParsedDocument(source_name=path.name, page_count=1, blocks=blocks)


def parse_document(path: str | Path) -> ParsedDocument:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        from app.knowledge.parsing.pdf_parser import parse_pdf
        return parse_pdf(file_path)
    if suffix == ".docx":
        from app.knowledge.parsing.docx_parser import parse_docx
        return parse_docx(file_path)
    if suffix == ".pptx":
        from app.knowledge.parsing.pptx_parser import parse_pptx
        return parse_pptx(file_path)
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return _parse_text(file_path)
    raise ValueError(
        f"Unsupported document suffix: {suffix} (supported: {sorted(SUPPORTED_SUFFIXES)})"
    )


__all__ = ["ParsedBlock", "ParsedDocument", "parse_document", "table_to_markdown",
           "SUPPORTED_SUFFIXES"]

"""Format-dispatching document parsing (Round B rework, spec B2.1; Round C
docs/rules 3.2 adds .txt heading detection and .csv).

parse_document(path) -> ParsedDocument for .pdf (pdfplumber), .docx
(python-docx), .pptx (python-pptx), plain text and .csv. No fallbacks between
libraries — a missing library is a loud ImportError, never a silent quality
downgrade.

.txt / .md: blank-line-separated blocks are paragraphs; a single line ending
in ':' OR written in title case is a heading (page_no=1 throughout, so the
section-boundary chunker derives section_path from the nearest heading via the
existing " > " trail).

.csv: the WHOLE file is ONE table block rendered as GitHub-flavoured markdown
— the chunker then emits it as a single has_table=true chunk, never split.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.knowledge.parsing.base import ParsedBlock, ParsedDocument, table_to_markdown

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md"}
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".pptx", ".csv"} | SUPPORTED_TEXT_SUFFIXES

# words a title-case heading may leave lowercase ("Change of Fee Schedule")
_MINOR_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of",
                "on", "or", "the", "to", "with"}


def _is_title_case(line: str) -> bool:
    """True for a short line whose alphabetic words are capitalised (minor
    words may stay lowercase). Sentence-like lines (ending . ! ?) never count."""
    if len(line) > 80 or line.endswith((".", "!", "?", ",", ";")):
        return False
    words = [w for w in line.split() if any(ch.isalpha() for ch in w)]
    if not words:
        return False
    for i, word in enumerate(words):
        stripped = word.strip("()[]\"'“”‘’")
        if not stripped:
            continue
        if stripped.lower() in _MINOR_WORDS and 0 < i < len(words) - 1:
            continue
        first_alpha = next((ch for ch in stripped if ch.isalpha()), "")
        if first_alpha and not first_alpha.isupper():
            return False
    return True


def _is_heading_line(line: str) -> bool:
    return line.endswith(":") or _is_title_case(line)


def _parse_text(path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    blocks: list[ParsedBlock] = []
    order = 0

    def emit(block_type: str, text: str, heading_level: int) -> None:
        nonlocal order
        blocks.append(ParsedBlock(
            block_type=block_type, text=text, page_no=1,
            heading_level=heading_level, order=order,
        ))
        order += 1

    for part in raw.split("\n\n"):
        lines = [ln.strip() for ln in part.splitlines() if ln.strip()]
        if not lines:
            continue
        # A single-line block that looks like a heading IS a heading (3.2);
        # a heading line opening a multi-line block heads that block's prose.
        if _is_heading_line(lines[0]) and len(lines) > 1:
            emit("heading", lines[0].rstrip(":").strip(), 1)
            lines = lines[1:]
        if len(lines) == 1 and _is_heading_line(lines[0]):
            emit("heading", lines[0].rstrip(":").strip(), 1)
        else:
            emit("paragraph", "\n".join(lines), 0)
    return ParsedDocument(source_name=path.name, page_count=1, blocks=blocks)


def _parse_csv(path: Path) -> ParsedDocument:
    """Round C (docs/rules) 3.2: the whole .csv is ONE table block, rendered as
    markdown; the chunker keeps tables whole, so it lands as one
    has_table=true chunk."""
    raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    rows = [row for row in csv.reader(io.StringIO(raw)) if any(c.strip() for c in row)]
    if not rows:
        return ParsedDocument(source_name=path.name, page_count=1, blocks=[])
    return ParsedDocument(source_name=path.name, page_count=1, blocks=[ParsedBlock(
        block_type="table", text=table_to_markdown(rows), page_no=1,
        heading_level=0, order=0,
    )])


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
    if suffix == ".csv":
        return _parse_csv(file_path)
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return _parse_text(file_path)
    raise ValueError(
        f"Unsupported document suffix: {suffix} (supported: {sorted(SUPPORTED_SUFFIXES)})"
    )


__all__ = ["ParsedBlock", "ParsedDocument", "parse_document", "table_to_markdown",
           "SUPPORTED_SUFFIXES"]

"""Shared parsing dataclasses (Round B rework, spec B2.1).

Every format parser (pdf/docx/pptx) emits the same block stream so the
section-boundary chunker is format-agnostic. Tables are rendered as
GitHub-flavoured markdown at parse time — table integrity is the single most
important property of this stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedBlock:
    block_type: str      # "heading" | "paragraph" | "table" | "list"
    text: str            # tables rendered as GitHub-flavoured markdown
    page_no: int
    heading_level: int   # 0 for non-headings
    order: int


@dataclass
class ParsedDocument:
    source_name: str
    page_count: int
    blocks: list[ParsedBlock] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Canonical extracted text — the sha256 idempotency hash is taken over
        this, so identical content always hashes identically regardless of the
        upload path."""
        return "\n\n".join(b.text for b in self.blocks if b.text.strip())


def _md_escape(cell: object) -> str:
    text = "" if cell is None else str(cell)
    return text.replace("\n", " ").replace("|", "\\|").strip()


def table_to_markdown(rows: list[list]) -> str:
    """Render extracted table rows as a GitHub-flavoured markdown table.

    First row is treated as the header. Ragged rows are padded so the table
    stays syntactically valid markdown."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [[_md_escape(c) for c in list(r) + [""] * (width - len(r))] for r in rows]
    header = "| " + " | ".join(norm[0]) + " |"
    separator = "| " + " | ".join(["---"] * width) + " |"
    body = ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join([header, separator, *body])

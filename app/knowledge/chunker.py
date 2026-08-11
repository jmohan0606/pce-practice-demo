"""Section-boundary chunker (Round B rework, spec B2.2). Replaces V1's
fixed 900-char sliding window.

Algorithm:
  1. Group blocks into sections: a heading starts a section and runs to the
     next heading of EQUAL OR HIGHER level. Blocks before the first heading
     form section "(preamble)".
  2. Each TABLE block becomes its OWN chunk — never split, never merged with
     prose. The section heading is prepended as context above the markdown.
  3. Prose within a section accumulates to CHUNK_MAX_CHARS (1800); longer
     sections split at paragraph boundaries with CHUNK_OVERLAP_CHARS (200) of
     trailing context.
  4. Every chunk carries: chunk_id = f"{document_id}-C{index:04d}", page_no of
     its first block, section_path (dotted heading trail), has_table,
     chunk_index.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.settings import get_settings
from app.knowledge.parsing.base import ParsedBlock

PREAMBLE = "(preamble)"


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    page_no: int
    section_path: str
    has_table: bool


@dataclass
class _Section:
    path: str            # dotted heading trail, e.g. "3. Sharing > 3.2 Discount Sharing"
    heading_text: str    # nearest heading, prepended to table chunks
    page_no: int
    blocks: list[ParsedBlock] = field(default_factory=list)


def _sections(blocks: list[ParsedBlock]) -> list[_Section]:
    sections: list[_Section] = []
    trail: list[tuple[int, str]] = []  # (level, heading text)
    current = _Section(path=PREAMBLE, heading_text="", page_no=blocks[0].page_no if blocks else 1)
    for block in blocks:
        if block.block_type == "heading":
            if current.blocks:
                sections.append(current)
            # an equal-or-higher heading pops the trail back to its level
            level = max(1, block.heading_level)
            trail = [(lv, tx) for lv, tx in trail if lv < level]
            trail.append((level, block.text.strip()))
            current = _Section(
                path=" > ".join(tx for _, tx in trail),
                heading_text=block.text.strip(),
                page_no=block.page_no,
            )
        else:
            if not current.blocks and current.path != PREAMBLE:
                # section page stays that of its heading; first content block
                # may sit on the next page — heading provenance wins.
                pass
            current.blocks.append(block)
    if current.blocks or (current.path != PREAMBLE and not sections):
        sections.append(current)
    return sections


class SectionChunker:
    def __init__(self, max_chars: int | None = None, overlap_chars: int | None = None) -> None:
        settings = get_settings()
        self.max_chars = max_chars if max_chars is not None else settings.chunk_max_chars
        self.overlap_chars = (
            overlap_chars if overlap_chars is not None else settings.chunk_overlap_chars
        )

    def chunk(self, document_id: str, blocks: list[ParsedBlock]) -> list[Chunk]:
        chunks: list[Chunk] = []

        def emit(text: str, page_no: int, section_path: str, has_table: bool) -> None:
            index = len(chunks)
            chunks.append(Chunk(
                chunk_id=f"{document_id}-C{index:04d}",
                document_id=document_id,
                chunk_index=index,
                text=text.strip(),
                page_no=page_no,
                section_path=section_path,
                has_table=has_table,
            ))

        for section in _sections(blocks):
            prose: list[ParsedBlock] = []

            def flush_prose() -> None:
                if not prose:
                    return
                self._emit_prose(prose, section, emit)
                prose.clear()

            for block in section.blocks:
                if block.block_type == "table":
                    flush_prose()
                    # A table is its OWN chunk: section heading as context,
                    # then the complete markdown table. Never split.
                    parts = [p for p in (section.heading_text, block.text) if p]
                    emit("\n\n".join(parts), block.page_no, section.path, has_table=True)
                else:
                    prose.append(block)
            flush_prose()
        return chunks

    def _emit_prose(self, prose: list[ParsedBlock], section: _Section, emit) -> None:
        """Accumulate paragraphs to max_chars; split at paragraph boundaries
        with overlap_chars of trailing context carried into the next chunk."""
        buffer: list[str] = []
        buffer_len = 0
        page_no = prose[0].page_no

        def flush() -> None:
            nonlocal buffer, buffer_len
            if buffer:
                emit("\n\n".join(buffer), page_no, section.path, has_table=False)

        for block in prose:
            text = block.text.strip()
            if not text:
                continue
            if buffer and buffer_len + len(text) + 2 > self.max_chars:
                flush()
                # trailing overlap from what was just emitted
                tail = "\n\n".join(buffer)[-self.overlap_chars:].lstrip()
                buffer = [tail] if tail else []
                buffer_len = len(tail)
                page_no = block.page_no
            elif not buffer:
                page_no = block.page_no
            # a single paragraph longer than max_chars still stays whole —
            # paragraph boundaries are the only split points (spec B2.2).
            buffer.append(text)
            buffer_len += len(text) + 2
        flush()

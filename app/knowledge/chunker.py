"""Fixed-size sliding-window text chunker (ported from V1's chunking.py).

NOTE (Round B): this chunking strategy is REPLACED in Round B by
section-boundary chunking that keeps tables whole and carries
page_no/section_path metadata. Until then this is a faithful V1 port.
"""

from __future__ import annotations

from app.knowledge.models import KnowledgeChunk


class TextChunker:
    def __init__(self, chunk_size: int = 900, overlap: int = 120) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, document_id: str, text: str) -> list[KnowledgeChunk]:
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not normalized:
            return []
        chunks = []
        start = 0
        index = 0
        while start < len(normalized):
            end = min(start + self.chunk_size, len(normalized))
            chunk_text = normalized[start:end]
            chunks.append(KnowledgeChunk(
                chunk_id=f"{document_id}_chunk_{index:04d}",
                document_id=document_id,
                chunk_index=index,
                chunk_text=chunk_text,
                chunk_summary=chunk_text[:180],
            ))
            index += 1
            if end == len(normalized):
                break
            start = max(0, end - self.overlap)
        return chunks

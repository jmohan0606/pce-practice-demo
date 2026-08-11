"""Knowledge ingestion + semantic search (Round B rework of the V1 port).

Round B changes (spec B2):
- parsing goes through app/knowledge/parsing/ (pdfplumber / python-docx /
  python-pptx) into ParsedBlock streams — tables survive as markdown;
- chunking is section-boundary (SectionChunker): tables are their own chunks,
  prose splits at paragraph boundaries with overlap, every chunk carries
  page_no / section_path / has_table;
- indexed documents are written to the graph (phx_dm_pce_document +
  phx_dm_pce_document_chunk) via DocumentGraphWriter — the V1 TigerGraph
  document linker's replacement (see DECISIONS.md);
- dual-write ordering: Chroma FIRST, then graph; on graph failure the
  document's Chroma entries are deleted before raising — never orphan vectors;
- status lifecycle uploaded -> parsed -> chunked -> embedded -> indexed |
  failed, recorded in the catalog at each stage.

Kept from V1 (must survive): sha256-of-extracted-text idempotency — the same
name + same content is skipped, never re-indexed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config.settings import get_settings
from app.knowledge.catalog import KnowledgeCatalogRepository
from app.knowledge.chunker import Chunk, SectionChunker
from app.knowledge.embedding import get_document_embedder
from app.knowledge.graph_writer import DocumentGraphWriter
from app.knowledge.models import (
    DEFAULT_COLLECTION,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeIngestionRequest,
    KnowledgeIngestionResult,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.knowledge.parsing import parse_document
from app.knowledge.vector_store import KnowledgeVectorStore
from app.shared.logging import get_logger

_log = get_logger("app.knowledge.service")


def _to_knowledge_chunk(chunk: Chunk, collection_name: str, document: KnowledgeDocument) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        chunk_text=chunk.text,
        chunk_summary=chunk.text[:180],
        page_no=chunk.page_no,
        section_path=chunk.section_path,
        has_table=chunk.has_table,
        metadata={
            "document_name": document.document_name,
            "document_category": document.document_category,
            "collection_name": collection_name,
            "page_no": chunk.page_no,
            "section_path": chunk.section_path,
            "has_table": chunk.has_table,
        },
    )


class KnowledgeManagementService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.chunker = SectionChunker()
        self.embedder = get_document_embedder()
        self.vector_store = KnowledgeVectorStore()
        self.catalog = KnowledgeCatalogRepository()
        self.graph_writer = DocumentGraphWriter()

    # ------------------------------------------------------------------ ingest
    def ingest_document(self, request: KnowledgeIngestionRequest) -> KnowledgeIngestionResult:
        if not request.source_path:
            raise ValueError("source_path is required")
        source_path = Path(request.source_path)
        collection = request.collection_name or DEFAULT_COLLECTION

        parsed = parse_document(source_path)
        text = parsed.full_text

        # Idempotency guard (V1, must survive): same name + same extracted
        # content never indexes twice.
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self.catalog.find_document(source_path.name, content_hash)
        if existing and existing.status != KnowledgeDocumentStatus.INDEXED:
            # A stale non-indexed record (e.g. a failed ingest) is not a
            # duplicate — clear it and retry cleanly.
            self.catalog.delete_document(existing.document_id)
            existing = None
        if existing:
            return KnowledgeIngestionResult(
                document=existing, chunks=[], collection_name=collection,
                indexed_count=0, status=existing.status,
                message=f"Skipped duplicate: '{source_path.name}' already indexed as "
                        f"{existing.document_id} with identical content (sha256 match).",
            )

        document_id = f"DOC_{uuid4().hex[:12]}"
        document = KnowledgeDocument(
            document_id=document_id,
            document_name=source_path.name,
            document_type=request.document_type,
            document_category=request.document_category,
            source_path=str(source_path),
            status=KnowledgeDocumentStatus.UPLOADED,
        )
        uploaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        base_meta = {
            "collection_name": collection,
            "content_hash": content_hash,
            "page_count": parsed.page_count,
        }
        self._record_status(document, base_meta)

        try:
            # parsed
            document.status = KnowledgeDocumentStatus.PARSED
            self._record_status(document, base_meta)

            # chunked
            chunks = self.chunker.chunk(document_id, parsed.blocks)
            table_chunk_count = sum(1 for c in chunks if c.has_table)
            base_meta.update({
                "chunk_count": len(chunks),
                "table_chunk_count": table_chunk_count,
            })
            document.status = KnowledgeDocumentStatus.CHUNKED
            self._record_status(document, base_meta)

            # embedded
            knowledge_chunks = [_to_knowledge_chunk(c, collection, document) for c in chunks]
            embeddings = self.embedder.embed_many([c.text for c in chunks]) if chunks else []
            document.status = KnowledgeDocumentStatus.EMBEDDED
            self._record_status(document, base_meta)

            # indexed — dual write, Chroma FIRST, then graph.
            indexed = self.vector_store.upsert_chunks(
                collection, knowledge_chunks, embeddings,
                document.document_name, document.document_category,
            ) if knowledge_chunks else 0
            try:
                self.graph_writer.write_document(
                    document_id=document_id,
                    document_name=document.document_name,
                    document_type=str(document.document_type),
                    page_count=parsed.page_count,
                    content_hash=content_hash,
                    status=KnowledgeDocumentStatus.INDEXED.value,
                    uploaded_at=uploaded_at,
                    chunks=chunks,
                    chroma_collection=collection,
                )
            except Exception:
                # Never orphan vectors: pull this document's Chroma entries
                # back out before surfacing the graph failure.
                self.vector_store.delete_document_chunks(collection, document_id)
                raise

            document.status = KnowledgeDocumentStatus.INDEXED
            self._record_status(document, {**base_meta, "indexed_count": indexed,
                                           "uploaded_at": uploaded_at})
            for chunk in knowledge_chunks:
                self.catalog.save_chunk(chunk.chunk_id, chunk.document_id, chunk.chunk_index,
                                        chunk.chunk_summary, chunk.metadata)
            return KnowledgeIngestionResult(
                document=document, chunks=knowledge_chunks, collection_name=collection,
                indexed_count=indexed, status=document.status, message="Document indexed.",
            )
        except Exception as exc:
            document.status = KnowledgeDocumentStatus.FAILED
            self._record_status(document, {**base_meta, "error": f"{type(exc).__name__}: {exc}"})
            _log.error("ingest failed for %s: %s", source_path.name, exc)
            raise

    def _record_status(self, document: KnowledgeDocument, metadata: dict) -> None:
        self.catalog.save_document(document, dict(metadata))

    # ------------------------------------------------------------------ delete
    def delete_document(self, document_id: str) -> dict:
        """Remove a document's chunks from Chroma AND the graph, then the
        catalog rows. Returns what was removed; unknown id -> found=False."""
        rows = [r for r in self.catalog.list_documents() if r["document_id"] == document_id]
        if not rows:
            return {"found": False, "document_id": document_id}
        import json as _json

        meta = _json.loads(rows[0].get("metadata_json") or "{}")
        collection = meta.get("collection_name") or DEFAULT_COLLECTION
        chunk_ids = self.catalog.chunk_ids_for_document(document_id)
        self.vector_store.delete_document_chunks(collection, document_id)
        graph_result = self.graph_writer.delete_document(document_id, chunk_ids)
        self.catalog.delete_document(document_id)
        return {
            "found": True,
            "document_id": document_id,
            "document_name": rows[0]["document_name"],
            "chunks_removed": len(chunk_ids),
            "graph": graph_result,
        }

    # ------------------------------------------------------------------ search
    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
        embedding = self.embedder.embed(request.query)
        results = self.vector_store.search(
            request.collection_name, embedding, request.query, request.top_k)
        if request.document_category:
            results = [r for r in results
                       if r.metadata.get("document_category") == request.document_category]
        return KnowledgeSearchResponse(query=request.query, results=results)

    # -------------------------------------------------------------------- list
    def list_documents(self) -> list[dict]:
        import json as _json

        rows = self.catalog.list_documents()
        out = []
        for row in rows:
            meta = _json.loads(row.get("metadata_json") or "{}")
            out.append({
                "document_id": row["document_id"],
                "document_name": row["document_name"],
                "document_type": row.get("document_type"),
                "document_category": row.get("document_category"),
                "status": row.get("status"),
                "uploaded_at": row.get("uploaded_at"),
                "page_count": meta.get("page_count"),
                "chunk_count": meta.get("chunk_count", 0),
                "table_chunk_count": meta.get("table_chunk_count", 0),
                "collection_name": meta.get("collection_name", DEFAULT_COLLECTION),
                "error": meta.get("error"),
            })
        return out

    def document_chunks(self, document_id: str) -> list[dict]:
        """All chunks of one document, in chunk_index order, shaped for the
        B3 Rule Extractor (chunk_id / chunk_text / page_no / section_path /
        has_table / chunk_index). Text comes from the graph vertex (source of
        truth for chunk_text); metadata from the catalog."""
        import json as _json

        rows = self.catalog.query(
            "SELECT * FROM phx_dm_pce_knowledge_chunk_catalog WHERE document_id = ? "
            "ORDER BY chunk_index ASC", (document_id,))
        graph_texts = self._graph_chunk_texts(document_id)
        # Round E fix: the graph mock store is process-local, so after a restart
        # a deduped document has NO graph chunk vertices and the old fallback
        # silently served the 180-char catalog summary — the extractor then saw
        # truncated provisions everywhere. Chroma persists the FULL text on
        # disk; use it as the second source and FAIL LOUDLY rather than ever
        # serving a truncated chunk as if it were the document.
        chroma_texts: dict[str, str] = {}
        chunks = []
        for row in rows:
            meta = _json.loads(row.get("metadata_json") or "{}")
            text = graph_texts.get(row["chunk_id"], "")
            if not text:
                if not chroma_texts:
                    collection = meta.get("collection_name") or DEFAULT_COLLECTION
                    chroma_texts = self.vector_store.document_chunk_texts(
                        collection, document_id)
                text = chroma_texts.get(row["chunk_id"], "")
            if not text:
                raise RuntimeError(
                    f"chunk {row['chunk_id']} of {document_id} has no full text in "
                    f"the graph or Chroma — refusing to serve the truncated "
                    f"catalog summary as document content")
            chunks.append({
                "chunk_id": row["chunk_id"],
                "document_id": document_id,
                "chunk_index": row["chunk_index"],
                "chunk_text": text,
                "page_no": meta.get("page_no"),
                "section_path": meta.get("section_path"),
                "has_table": meta.get("has_table", False),
            })
        return chunks

    def _graph_chunk_texts(self, document_id: str) -> dict[str, str]:
        try:
            result = self.graph_writer.graph.fetch_vertices(
                "phx_dm_pce_document_chunk", limit=100_000)
            return {
                row["v_id"]: row["attributes"].get("chunk_text", "")
                for row in result.get("results", [])
                if row["attributes"].get("document_id") == document_id
            }
        except Exception:  # noqa: BLE001 — catalog summary is the fallback
            return {}

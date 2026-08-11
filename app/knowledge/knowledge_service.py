"""Knowledge ingestion + semantic search (ported from V1's
knowledge_management_service.py).

Changes from V1: embeddings come from the shared EmbeddingClient adapter
(app.llm.embedding_client), the TigerGraph document linker is dropped, and the
V1 filename-based category heuristics are removed ("Comp Plan" default).

NOTE (Round B): the chunking strategy this service uses is replaced in Round B
(section-boundary chunking, tables kept whole, page_no/section_path metadata).

TODO (Round B): graph document vertices — V1 linked each indexed document into
TigerGraph via a document linker; in this build the document/chunk vertices are
written in Round B through the pce graph schema instead.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from app.config.settings import get_settings
from app.knowledge.catalog import KnowledgeCatalogRepository
from app.knowledge.chunker import TextChunker
from app.knowledge.document_parser import DocumentParser
from app.knowledge.models import (
    DEFAULT_COLLECTION,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeIngestionRequest,
    KnowledgeIngestionResult,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.knowledge.vector_store import KnowledgeVectorStore
from app.llm.embedding_client import get_embedding_client


class KnowledgeManagementService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.parser = DocumentParser()
        self.chunker = TextChunker()
        self.embedder = get_embedding_client()
        self.vector_store = KnowledgeVectorStore()
        self.catalog = KnowledgeCatalogRepository()

    def ingest_document(self, request: KnowledgeIngestionRequest) -> KnowledgeIngestionResult:
        if not request.source_path:
            raise ValueError("source_path is required")
        source_path = Path(request.source_path)
        text = self.parser.parse(source_path)

        # Idempotency guard: the same file content under the same name must not index
        # twice (root cause of the V1 corpus reaching 10 copies of every document —
        # repeated ingest calls each minted a fresh DOC_<uuid>).
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self.catalog.find_document(source_path.name, content_hash)
        if existing:
            return KnowledgeIngestionResult(
                document=existing, chunks=[], collection_name=request.collection_name,
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
            status=KnowledgeDocumentStatus.PARSED,
        )
        chunks = self.chunker.chunk_text(document_id, text)
        for chunk in chunks:
            chunk.metadata.update({
                "document_name": document.document_name,
                "document_category": document.document_category,
                "collection_name": request.collection_name,
            })
        embeddings = self.embedder.embed_many([c.chunk_text for c in chunks]) if chunks else []
        indexed = self.vector_store.upsert_chunks(request.collection_name, chunks, embeddings, document.document_name, document.document_category)
        document.status = KnowledgeDocumentStatus.INDEXED
        self.catalog.save_document(document, {"collection_name": request.collection_name, "chunk_count": len(chunks), "indexed_count": indexed, "content_hash": content_hash})
        for chunk in chunks:
            self.catalog.save_chunk(chunk.chunk_id, chunk.document_id, chunk.chunk_index, chunk.chunk_summary, chunk.metadata)
        return KnowledgeIngestionResult(document=document, chunks=chunks, collection_name=request.collection_name, indexed_count=indexed, status=document.status, message="Document indexed.")

    def dedupe_corpus(self) -> dict:
        """Remove duplicate documents (same document_name) from the catalog AND the
        vector index, keeping the earliest copy of each. One-time repair for a
        pre-idempotency corpus where a document was ingested repeatedly."""
        import json as _json
        docs = self.catalog.list_documents()
        by_name: dict[str, list[dict]] = {}
        for row in docs:
            by_name.setdefault(row["document_name"], []).append(row)
        removed, kept = [], []
        for name, rows in by_name.items():
            rows.sort(key=lambda r: r.get("uploaded_at") or "")
            kept.append(rows[0]["document_id"])
            for dup in rows[1:]:
                meta = _json.loads(dup.get("metadata_json") or "{}")
                collection = meta.get("collection_name") or DEFAULT_COLLECTION
                self.vector_store.delete_document_chunks(collection, dup["document_id"])
                self.catalog.delete_document(dup["document_id"])
                removed.append({"document_id": dup["document_id"], "document_name": name})
        return {"documents_before": len(docs), "documents_kept": len(kept),
                "duplicates_removed": len(removed), "removed": removed}

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
        embedding = self.embedder.embed(request.query)
        results = self.vector_store.search(request.collection_name, embedding, request.query, request.top_k)
        if request.document_category:
            results = [r for r in results if r.metadata.get("document_category") == request.document_category]
        return KnowledgeSearchResponse(query=request.query, results=results)

    def list_documents(self) -> list[dict]:
        return self.catalog.list_documents()

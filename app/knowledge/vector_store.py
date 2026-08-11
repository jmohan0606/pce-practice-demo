"""Chroma-backed vector store for knowledge chunks (ported from V1)."""

from __future__ import annotations

from app.knowledge.chroma_client import ChromaClientFactory
from app.knowledge.models import KnowledgeChunk, KnowledgeSearchResult


class KnowledgeVectorStore:
    def __init__(self) -> None:
        self.factory = ChromaClientFactory()

    def upsert_chunks(self, collection_name: str, chunks: list[KnowledgeChunk], embeddings: list[list[float]], document_name: str, document_category: str) -> int:
        collection = self.factory.get_or_create_collection(collection_name)
        collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.chunk_text for c in chunks],
            embeddings=embeddings,
            metadatas=[{
                **c.metadata,
                "document_id": c.document_id,
                "document_name": document_name,
                "document_category": document_category,
                "chunk_index": c.chunk_index,
            } for c in chunks],
        )
        return len(chunks)

    def delete_document_chunks(self, collection_name: str, document_id: str) -> None:
        collection = self.factory.get_or_create_collection(collection_name)
        collection.delete(where={"document_id": document_id})

    def search(self, collection_name: str, query_embedding: list[float], query_text: str, top_k: int = 5) -> list[KnowledgeSearchResult]:
        collection = self.factory.get_or_create_collection(collection_name)
        result = collection.query(query_embeddings=[query_embedding], query_texts=[query_text], n_results=top_k)
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0] if result.get("distances") else [None] * len(ids)
        out = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists):
            out.append(KnowledgeSearchResult(
                chunk_id=cid,
                document_id=meta.get("document_id", ""),
                document_name=meta.get("document_name", ""),
                chunk_text=doc,
                # Collection uses cosine distance; report cosine similarity so
                # higher = more relevant everywhere downstream.
                score=None if dist is None else round(1.0 - float(dist), 4),
                metadata=meta,
            ))
        return out

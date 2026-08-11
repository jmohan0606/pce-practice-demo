"""Pydantic models for the knowledge / RAG module (ported from V1)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

DEFAULT_COLLECTION = "pce_knowledge_base"


class KnowledgeDocumentType(StrEnum):
    COMP_PLAN = "Comp Plan"
    PRACTICE_GUIDELINE = "Practice Guideline"
    COMPLIANCE_POLICY = "Compliance Policy"
    PLAYBOOK = "Playbook"
    GLOSSARY = "Glossary"
    RESEARCH = "Research"
    OTHER = "Other"


class KnowledgeDocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSED = "parsed"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    FAILED = "failed"


class KnowledgeDocument(BaseModel):
    document_id: str
    document_name: str
    document_type: KnowledgeDocumentType = KnowledgeDocumentType.OTHER
    document_category: str = "Comp Plan"
    source_path: str
    version: str = "1.0"
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.UPLOADED
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeChunk(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    chunk_text: str
    chunk_summary: str | None = None
    metadata: dict = Field(default_factory=dict)


class KnowledgeIngestionRequest(BaseModel):
    source_path: str | None = None
    document_type: KnowledgeDocumentType = KnowledgeDocumentType.OTHER
    document_category: str = "Comp Plan"
    collection_name: str = DEFAULT_COLLECTION


class KnowledgeIngestionResult(BaseModel):
    document: KnowledgeDocument
    chunks: list[KnowledgeChunk]
    collection_name: str
    indexed_count: int
    status: KnowledgeDocumentStatus
    message: str


class KnowledgeSearchRequest(BaseModel):
    query: str
    collection_name: str = DEFAULT_COLLECTION
    top_k: int = 5
    document_category: str | None = None


class KnowledgeSearchResult(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    chunk_text: str
    score: float | None = None
    metadata: dict = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeSearchResult] = Field(default_factory=list)

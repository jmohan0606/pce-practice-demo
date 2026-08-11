"""Pydantic models for the knowledge / RAG module (ported from V1)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# Round B (spec B2.3): the plan-document corpus lives in ONE Chroma collection.
DEFAULT_COLLECTION = "pce_plan_documents"


class KnowledgeDocumentType(StrEnum):
    # 5.2: the two types the upload UI offers. Only PLAN documents go to the
    # Rule Extractor; both are chunked and embedded into Chroma.
    PLAN = "PLAN"
    GUIDANCE = "GUIDANCE"
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
    # Round B provenance (spec B2.2) — page_no must never be wrong.
    page_no: int = 1
    section_path: str = "(preamble)"
    has_table: bool = False
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

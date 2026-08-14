"""Pydantic models for the knowledge / RAG module (ported from V1)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# Round B (spec B2.3): the plan-document corpus lives in ONE Chroma collection.
DEFAULT_COLLECTION = "pce_plan_documents"


# Round C (docs/rules) 3.1 — the six document categories the upload UI offers.
# ONLY the extracting categories feed the Rule Extractor (FAQ is included
# because the client's own 2026 Changes FAQ contains rules); everything else is
# chunked, embedded and searchable but never produces rules.
DOCUMENT_CATEGORIES = ("PLAN", "GUIDANCE", "PLAYBOOK", "TRAINING", "FAQ", "OTHER")
EXTRACTING_CATEGORIES = ("PLAN", "FAQ")


class KnowledgeDocumentType(StrEnum):
    # Round C (docs/rules) 3.1: the six categories, chosen at upload (default
    # PLAN) and editable afterwards. Only PLAN and FAQ go to the Rule
    # Extractor; all six are chunked and embedded into Chroma.
    PLAN = "PLAN"
    GUIDANCE = "GUIDANCE"
    PLAYBOOK = "PLAYBOOK"
    TRAINING = "TRAINING"
    FAQ = "FAQ"
    OTHER = "OTHER"
    # Legacy V1 values — kept so pre-Round-C catalog rows still parse.
    COMP_PLAN = "Comp Plan"
    PRACTICE_GUIDELINE = "Practice Guideline"
    COMPLIANCE_POLICY = "Compliance Policy"
    GLOSSARY = "Glossary"
    RESEARCH = "Research"

    @classmethod
    def _missing_(cls, value: object):  # case-insensitive ("Playbook" -> PLAYBOOK)
        if isinstance(value, str):
            folded = value.strip().upper()
            for member in cls:
                if member.value.upper() == folded or member.name == folded:
                    return member
        return None


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

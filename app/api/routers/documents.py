"""Documents & RAG endpoints (Round B, spec B2.4).

POST   /api/documents/upload                multipart, multiple files
GET    /api/documents                       list with status and counts
DELETE /api/documents/{id}                  removes chunks from Chroma AND graph
PATCH  /api/documents/{id}/category         edit category; extraction_offered
POST   /api/documents/{id}/extract-rules    triggers the Rule Extractor (B3; PLAN/FAQ only)
GET    /api/documents/search?q=&top_k=5     retrieval check (chunks + similarity)

The search endpoint is retrieval-only: it NEVER calls an LLM. Below the 0.30
cosine floor it returns found=false honestly (spec: no fabricated answers).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config.settings import get_settings, resolve_app_path
from app.knowledge.knowledge_service import KnowledgeManagementService
from app.knowledge.models import (
    DEFAULT_COLLECTION,
    DOCUMENT_CATEGORIES,
    EXTRACTING_CATEGORIES,
    KnowledgeIngestionRequest,
)
from app.knowledge.parsing import SUPPORTED_SUFFIXES
from app.knowledge.rag_service import RagGenerationService
from app.shared.logging import get_logger

_log = get_logger("app.api.documents")

router = APIRouter(prefix="/api/documents", tags=["documents"])


@lru_cache
def _service() -> KnowledgeManagementService:
    return KnowledgeManagementService()


@lru_cache
def _rag() -> RagGenerationService:
    return RagGenerationService()


def _counts_for(document_id: str) -> dict:
    for row in _service().list_documents():
        if row["document_id"] == document_id:
            return row
    return {}


def _validated_category(category: str) -> str:
    """Round C (docs/rules) 3.1 — category is validated EVERYWHERE it enters;
    unknown category is a 400 naming the valid set."""
    normalized = str(category or "").strip().upper()
    if normalized not in DOCUMENT_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown document category {category!r} — valid categories "
                   f"are {', '.join(DOCUMENT_CATEGORIES)}.")
    return normalized


def _refuse_non_extracting(document_id: str, category: str) -> None:
    """Only PLAN and FAQ feed the Rule Extractor — every route that can
    trigger extraction refuses other categories with an honest error naming
    the category."""
    if category in EXTRACTING_CATEGORIES:
        return
    raise HTTPException(
        status_code=400,
        detail=f"Document '{document_id}' is {category} — {category} documents "
               f"are indexed and searchable but never produce rules. Only "
               f"{' and '.join(EXTRACTING_CATEGORIES)} documents feed the "
               f"Rule Extractor.")


@router.post("/upload")
async def upload_documents(files: list[UploadFile] = File(...),
                           document_type: str = Form("PLAN")) -> dict:
    # Round C (docs/rules) 3.1: six categories, chosen at upload (default
    # PLAN). Only PLAN and FAQ go to the Rule Extractor; all six are chunked
    # + embedded and searchable.
    document_type = _validated_category(document_type or "PLAN")
    uploads_dir = resolve_app_path(get_settings().uploads_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for upload in files:
        name = Path(upload.filename or "unnamed").name
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported file type '{suffix}' for '{name}' "
                       f"(supported: {sorted(SUPPORTED_SUFFIXES)})",
            )
        target = uploads_dir / name
        target.write_bytes(await upload.read())
        try:
            from app.knowledge.models import KnowledgeDocumentType

            result = _service().ingest_document(KnowledgeIngestionRequest(
                source_path=str(target), collection_name=DEFAULT_COLLECTION,
                document_type=KnowledgeDocumentType(document_type),
            ))
        except Exception as exc:  # noqa: BLE001 — surfaced honestly per file
            _log.error("upload failed for %s: %s", name, exc)
            raise HTTPException(status_code=500,
                                detail=f"Ingestion failed for '{name}': {exc}") from exc
        skipped = result.indexed_count == 0 and result.message.startswith("Skipped duplicate")
        counts = _counts_for(result.document.document_id)
        results.append({
            "document_id": result.document.document_id,
            "document_name": result.document.document_name,
            "document_type": document_type,
            "page_count": counts.get("page_count"),
            "chunk_count": counts.get("chunk_count", len(result.chunks)),
            "table_chunk_count": counts.get("table_chunk_count",
                                            sum(1 for c in result.chunks if c.has_table)),
            "status": result.status.value,
            "skipped_duplicate": skipped,
        })
    return {"documents": results}


@router.get("")
def list_documents() -> dict:
    return {"documents": _service().list_documents()}


@router.delete("/{document_id}")
def delete_document(document_id: str) -> dict:
    result = _service().delete_document(document_id)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Unknown document_id '{document_id}'")
    return result


class CategoryRequest(BaseModel):
    category: str


@router.patch("/{document_id}/category")
def set_document_category(document_id: str, body: CategoryRequest) -> dict:
    """Round C (docs/rules) 3.1 — change a document's category after upload.
    extraction_offered=true iff the NEW category feeds the Rule Extractor
    (PLAN or FAQ) — the UI then offers to run extraction; nothing runs here."""
    category = _validated_category(body.category)
    document = _service().set_document_category(document_id, category)
    if document is None:
        raise HTTPException(status_code=404,
                            detail=f"Unknown document_id '{document_id}'")
    return {"document": document,
            "extraction_offered": category in EXTRACTING_CATEGORIES}


@router.post("/{document_id}/extract-rules")
def extract_rules(document_id: str, resume: bool = False) -> dict:
    # Round C (docs/rules) 3.1: only PLAN and FAQ feed the Rule Extractor.
    doc_row = _counts_for(document_id)
    if not doc_row:
        raise HTTPException(status_code=404,
                            detail=f"Unknown document_id '{document_id}'")
    doc_type = str(doc_row.get("document_type") or "PLAN").upper()
    _refuse_non_extracting(document_id, doc_type)
    chunks = _service().document_chunks(document_id)
    if not chunks:
        raise HTTPException(status_code=404,
                            detail=f"No chunks found for document '{document_id}'")
    # B3's Rule Extractor is built in parallel — imported lazily so this router
    # loads (and every other endpoint works) even before/without
    # app/agents/rule_extractor.py. Contract (reconciled with B3):
    #   extract_rules_for_document(document_id: str, chunks: list[dict]) -> list[dict]
    # where each chunk dict carries chunk_id, text, page_no, section_path, has_table.
    try:
        from app.agents.rule_extractor import extract_with_job
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Rule extraction is not available yet: the B3 Rule Extractor "
                   f"(app.agents.rule_extractor) could not be imported ({exc}). "
                   "It is being built in parallel and will be wired at integration time.",
        ) from exc
    extractor_chunks = [{**c, "text": c["chunk_text"]} for c in chunks]
    # Round 1 (schema freeze): extraction runs under a phx_dm_pce_job with
    # per-window resume; ?resume=1 restarts an INTERRUPTED job at its recorded
    # window (resume is explicit, never automatic).
    try:
        result = extract_with_job(document_id, extractor_chunks, resume=resume)
    except ValueError as exc:  # nothing-to-resume — a request error, not a 500
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"document_id": document_id, "chunk_count": len(chunks),
            "job": {k: result["job"].get(k) for k in
                    ("job_id", "status", "stage", "stage_index", "stage_total",
                     "items_done", "items_total")},
            "draft_rules": result["rules"]}


@router.get("/search")
def search_documents(q: str, top_k: int = 5) -> dict:
    if not q.strip():
        raise HTTPException(status_code=422, detail="Query parameter 'q' must be non-empty")
    rag = _rag()
    sources = rag.retrieve(q, top_k=top_k)  # floor 0.30 applied inside; NO LLM call
    return {
        "query": q,
        "top_k": top_k,
        "min_similarity": rag.MIN_SIMILARITY,
        "found": bool(sources),
        "results": [{
            "chunk_id": s["chunk_id"],
            "document_id": s["document_id"],
            "document_name": s["document_name"],
            "similarity": s["similarity"],
            "page_no": s.get("page_no"),
            "section_path": s.get("section_path"),
            "has_table": s.get("has_table"),
            "excerpt": s["excerpt"],
        } for s in sources],
    }

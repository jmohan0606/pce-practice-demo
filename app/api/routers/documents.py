"""Documents & RAG endpoints (Round B, spec B2.4).

POST   /api/documents/upload                multipart, multiple files
GET    /api/documents                       list with status and counts
DELETE /api/documents/{id}                  removes chunks from Chroma AND graph
POST   /api/documents/{id}/extract-rules    triggers the Rule Extractor (B3)
GET    /api/documents/search?q=&top_k=5     retrieval check (chunks + similarity)

The search endpoint is retrieval-only: it NEVER calls an LLM. Below the 0.30
cosine floor it returns found=false honestly (spec: no fabricated answers).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config.settings import get_settings, resolve_app_path
from app.knowledge.knowledge_service import KnowledgeManagementService
from app.knowledge.models import DEFAULT_COLLECTION, KnowledgeIngestionRequest
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


@router.post("/upload")
async def upload_documents(files: list[UploadFile] = File(...)) -> dict:
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
            result = _service().ingest_document(KnowledgeIngestionRequest(
                source_path=str(target), collection_name=DEFAULT_COLLECTION,
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


@router.post("/{document_id}/extract-rules")
def extract_rules(document_id: str) -> dict:
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
        from app.agents.rule_extractor import extract_rules_for_document
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Rule extraction is not available yet: the B3 Rule Extractor "
                   f"(app.agents.rule_extractor) could not be imported ({exc}). "
                   "It is being built in parallel and will be wired at integration time.",
        ) from exc
    extractor_chunks = [{**c, "text": c["chunk_text"]} for c in chunks]
    draft_rules = extract_rules_for_document(document_id=document_id, chunks=extractor_chunks)
    return {"document_id": document_id, "chunk_count": len(chunks),
            "draft_rules": draft_rules}


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

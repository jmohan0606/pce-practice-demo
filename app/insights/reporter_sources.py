"""Round E task 5 — the Reporter's ONE capability: document search.

The Reporter stays findings-only *by construction* in its own module
(``app/agents/insights_reporter.py`` still imports json/logging/re/typing and
nothing else — verify_round_c C6-9 keeps asserting that). The relaxation the
spec required is done by INJECTION: this module builds a ``search_documents``
callable and the service passes it into ``report()``. The Reporter can fetch a
threshold and its citation instead of recalling it, but it still has no graph
client, no tools object and no ability to import its way to one.

Two sources (ROUND_E_SPEC task 5):
- PLAN documents     -> thresholds, rules, qualifications
- GUIDANCE documents -> recommended practice, quoted with its citation

Every call is logged to the run's agent_query_log under agent_name
``insights_reporter`` (query_name ``search_documents``), same as the Miner's.
"""
from __future__ import annotations

import time

from app.insights.store import get_insight_store
from app.shared.logging import get_logger

_log = get_logger("app.insights.reporter_sources")

SOURCES = ("PLAN", "GUIDANCE")


def build_reporter_search(run_id: str):
    """A ``search_documents(query, source, top_k)`` callable scoped to one run.

    Returns citation dicts: document_id/name/type, chunk_id, page_no,
    section_path, excerpt, similarity. ``source`` filters to PLAN or GUIDANCE
    documents (the document vertex's document_type, normalised to upper)."""
    store = get_insight_store()

    def search_documents(query: str, source: str = "PLAN", top_k: int = 5) -> list[dict]:
        from app.knowledge.knowledge_service import KnowledgeManagementService
        from app.knowledge.rag_service import RagGenerationService

        wanted = str(source or "PLAN").upper()
        if wanted not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        start = time.perf_counter()
        # Same convention as the extract-rules endpoint (5.2): GUIDANCE is the
        # special class; every other document_type (PLAN, legacy 'Other', 'Comp
        # Plan', ...) is plan material.
        doc_types = {d["document_id"]:
                     ("GUIDANCE" if str(d.get("document_type") or "").upper() == "GUIDANCE"
                      else "PLAN")
                     for d in KnowledgeManagementService().list_documents()}
        # over-fetch, then filter by document type — the vector store does not
        # index document_type, only document_category
        hits = RagGenerationService().retrieve(str(query or ""), top_k=max(int(top_k) * 3, 6))
        rows = []
        for s in hits:
            if doc_types.get(s.get("document_id"), "PLAN") != wanted:
                continue
            rows.append({
                "document_id": s.get("document_id"),
                "document_name": s.get("document_name"),
                "document_type": wanted,
                "chunk_id": s.get("chunk_id"),
                "page_no": s.get("page_no"),
                "section_path": s.get("section_path"),
                "excerpt": (s.get("excerpt") or "")[:600],
                "similarity": s.get("similarity"),
            })
            if len(rows) >= int(top_k):
                break
        store.log_query(run_id, "insights_reporter", "search_documents",
                        {"query": str(query or ""), "source": wanted, "top_k": int(top_k)},
                        len(rows), (time.perf_counter() - start) * 1000)
        return rows

    return search_documents

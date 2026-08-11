"""Retrieval-augmented generation over the knowledge base (ported from V1)."""

from __future__ import annotations

from app.knowledge.models import DEFAULT_COLLECTION, KnowledgeSearchRequest

# SPY POINT (verify_round_b check 10): every LLM call this module can make goes
# through this ONE module-level name. Patch `app.knowledge.rag_service.get_llm_client`
# with a spy and it observes exactly the calls made — the honest not-found path
# below the 0.30 floor must trigger it ZERO times.
from app.llm.client import get_llm_client


class RagGenerationService:
    """Retrieval-augmented generation over the knowledge base.

    The single real RAG path: retrieve top-k semantically-embedded chunks,
    build a grounded prompt, generate through the LLMClient adapter, and return
    the answer WITH the cited chunks/documents — same evidence bar as every
    other pipeline stage. Callable from agents, services and routers alike;
    not a page-facing endpoint wrapper.
    """

    # Cosine-similarity floor below which a chunk is not evidence, just noise.
    MIN_SIMILARITY = 0.30

    def __init__(self) -> None:
        # Imported lazily to avoid circular imports.
        from app.knowledge.knowledge_service import KnowledgeManagementService

        self.knowledge = KnowledgeManagementService()

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        collection_name: str = DEFAULT_COLLECTION,
        document_category: str | None = None,
        min_similarity: float | None = None,
    ) -> list[dict]:
        """Top-k chunks above the relevance floor, as citable source dicts."""
        threshold = self.MIN_SIMILARITY if min_similarity is None else min_similarity
        response = self.knowledge.search(KnowledgeSearchRequest(
            query=query,
            collection_name=collection_name,
            top_k=top_k,
            document_category=document_category,
        ))
        sources = []
        for result in response.results:
            if result.score is not None and result.score < threshold:
                continue
            sources.append({
                "chunk_id": result.chunk_id,
                "document_id": result.document_id,
                "document_name": result.document_name,
                "document_category": result.metadata.get("document_category", ""),
                "similarity": result.score,
                "excerpt": result.chunk_text,
                # Round B provenance (spec B2.2) — carried through Chroma metadata.
                "page_no": result.metadata.get("page_no"),
                "section_path": result.metadata.get("section_path"),
                "has_table": bool(result.metadata.get("has_table", False)),
            })
        return sources

    def answer(
        self,
        question: str,
        top_k: int = 5,
        collection_name: str = DEFAULT_COLLECTION,
        document_category: str | None = None,
        min_similarity: float | None = None,
    ) -> dict:
        """Full RAG: retrieve -> grounded prompt -> LLMClient -> answer + citations."""
        threshold = self.MIN_SIMILARITY if min_similarity is None else min_similarity
        sources = self.retrieve(question, top_k, collection_name, document_category, threshold)

        retrieval = {
            "top_k": top_k,
            "min_similarity": threshold,
            "collection_name": collection_name,
            "sources_used": len(sources),
        }
        if not sources:
            # Honest not-found: no LLM call, no fabricated answer.
            return {
                "question": question,
                "found": False,
                "answer": (
                    "No relevant guidance was found in the knowledge base for this "
                    "question (no document passage cleared the similarity threshold "
                    f"of {threshold}). Try rephrasing, or ingest a document that covers this topic."
                ),
                "sources": [],
                "generated_by": {"mode": "none", "reason": "no passages above threshold"},
                "retrieval": retrieval,
            }

        passages = "\n\n".join(
            f"[{i}] {s['document_name']} ({s['document_category']}, similarity {s['similarity']}):\n{s['excerpt']}"
            for i, s in enumerate(sources, start=1)
        )
        context = {
            "system_prompt": (
                "You are the compensation-plan knowledge assistant for a practice "
                "management platform. Answer the question using ONLY the numbered "
                "source passages provided, which come from comp-plan and practice "
                "documents. Cite passages inline as [1], [2] etc. wherever you use "
                "them. If the passages only partially answer the question, say what "
                "is missing — never invent policy, figures or guidance that is not "
                "in the passages."
            ),
            "source_passages": passages,
        }
        llm = get_llm_client()
        answer_text = llm.generate(f"Question: {question}", context)
        return {
            "question": question,
            "found": True,
            "answer": answer_text,
            "sources": sources,
            "generated_by": llm.describe(),
            "retrieval": retrieval,
        }

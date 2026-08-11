"""Graph writes for indexed documents (Round B, spec B2.3 + DECISIONS.md).

V1's TigerGraphDocumentLinker was dropped in the Round A port; this module is
its replacement — the upload path writes phx_dm_pce_document and
phx_dm_pce_document_chunk vertices (plus the phx_dm_pce_chunk_of_document
edge) directly through the tiered graph client.

Dual-write ordering is enforced by the caller (KnowledgeManagementService):
Chroma first, then these graph writes; on graph failure the caller deletes the
document's Chroma entries before raising — never orphan vectors.
"""

from __future__ import annotations

from app.graph.client import get_graph_client
from app.knowledge.chunker import Chunk

DOCUMENT_VERTEX = "phx_dm_pce_document"
CHUNK_VERTEX = "phx_dm_pce_document_chunk"
CHUNK_OF_DOCUMENT_EDGE = "phx_dm_pce_chunk_of_document"

_DOCUMENT_ENTRY = {
    "kind": "vertex",
    "target": DOCUMENT_VERTEX,
    "id_column": "document_id",
    "file": "runtime:documents_upload",
    "columns": {
        "document_id": "document_id",
        "document_name": "document_name",
        "document_type": "document_type",
        "page_count": "page_count",
        "content_hash": "content_hash",
        "status": "status",
        "uploaded_at": "uploaded_at",
    },
}

_CHUNK_ENTRY = {
    "kind": "vertex",
    "target": CHUNK_VERTEX,
    "id_column": "chunk_id",
    "file": "runtime:documents_upload",
    "columns": {
        "chunk_id": "chunk_id",
        "document_id": "document_id",
        "chunk_index": "chunk_index",
        "page_no": "page_no",
        "section_path": "section_path",
        "chunk_text": "chunk_text",
        "has_table": "has_table",
        "chroma_collection": "chroma_collection",
    },
}

_CHUNK_EDGE_ENTRY = {
    "kind": "edge",
    "target": CHUNK_OF_DOCUMENT_EDGE,
    "from_type": CHUNK_VERTEX,
    "to_type": DOCUMENT_VERTEX,
    "from_column": "from_id",
    "to_column": "to_id",
    "file": "runtime:documents_upload",
    "columns": {},
}


class DocumentGraphWriter:
    def __init__(self) -> None:
        self.graph = get_graph_client()

    def write_document(
        self,
        document_id: str,
        document_name: str,
        document_type: str,
        page_count: int,
        content_hash: str,
        status: str,
        uploaded_at: str,
        chunks: list[Chunk],
        chroma_collection: str,
    ) -> dict:
        """Upsert the document vertex, all chunk vertices and the
        chunk->document edges. Raises GraphClientError on failure."""
        doc_result = self.graph.upsert(_DOCUMENT_ENTRY, [{
            "document_id": document_id,
            "document_name": document_name,
            "document_type": document_type,
            "page_count": page_count,
            "content_hash": content_hash,
            "status": status,
            "uploaded_at": uploaded_at,
        }])
        chunk_rows = [{
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "chunk_index": c.chunk_index,
            "page_no": c.page_no,
            "section_path": c.section_path,
            "chunk_text": c.text,
            "has_table": c.has_table,
            "chroma_collection": chroma_collection,
        } for c in chunks]
        chunk_result = self.graph.upsert(_CHUNK_ENTRY, chunk_rows) if chunk_rows else {}
        edge_rows = [{"from_id": c.chunk_id, "to_id": c.document_id} for c in chunks]
        edge_result = self.graph.upsert(_CHUNK_EDGE_ENTRY, edge_rows) if edge_rows else {}
        return {"document": doc_result, "chunks": chunk_result, "edges": edge_result}

    def update_status(self, document_id: str, document_name: str, document_type: str,
                      page_count: int, content_hash: str, status: str, uploaded_at: str) -> None:
        self.graph.upsert(_DOCUMENT_ENTRY, [{
            "document_id": document_id,
            "document_name": document_name,
            "document_type": document_type,
            "page_count": page_count,
            "content_hash": content_hash,
            "status": status,
            "uploaded_at": uploaded_at,
        }])

    def delete_document(self, document_id: str, chunk_ids: list[str]) -> dict:
        """Remove the chunk vertices and the document vertex (edges go with
        their endpoints). Best-effort per type; returns what was deleted."""
        chunks_result = self.graph.delete_vertices(CHUNK_VERTEX, chunk_ids) if chunk_ids else {}
        doc_result = self.graph.delete_vertices(DOCUMENT_VERTEX, [document_id])
        return {"chunks": chunks_result, "document": doc_result}

"""Chroma persistent-client factory (ported from V1)."""

from __future__ import annotations

from app.config.settings import get_settings, resolve_app_path


class ChromaClientFactory:
    def __init__(self) -> None:
        self.settings = get_settings()

    def create_client(self):
        import chromadb

        return chromadb.PersistentClient(path=str(resolve_app_path(self.settings.chroma_path)))

    def get_or_create_collection(self, collection_name: str):
        # Cosine space so scores are comparable across models; embeddings are
        # L2-normalized by the EmbeddingClient implementations.
        return self.create_client().get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )

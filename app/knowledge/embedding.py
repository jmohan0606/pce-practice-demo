"""Embedding access for the knowledge module.

The REAL path is the shared app.llm.embedding_client (EMBEDDING_MODE=cdao ->
text-embedding-3-large-1, EMBEDDING_DIM=3072, _fit_dim loud failure) — nothing
here bypasses it. This module adds ONE thing: EMBEDDING_MODE=mock for build
boxes without the cdao package. The mock is a deterministic hashed
bag-of-words vector, L2-normalised into the SAME dimension the real model
uses, so cosine-space code paths (floor 0.30, honest not-found) exercise
identically. It is clearly labelled mock in describe() — never a silent
stand-in for the real model.
"""

from __future__ import annotations

import hashlib
import math
import re

from app.config.settings import get_settings

_TOKEN = re.compile(r"[a-z0-9]+")


class MockEmbeddingClient:
    """Deterministic hashed bag-of-words embedding (EMBEDDING_MODE=mock only)."""

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            vector[0] = 1.0
            norm = 1.0
        return [v / norm for v in vector]

    def embed(self, text: str) -> list[float]:
        return self._vector(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def describe(self) -> dict:
        return {"mode": "mock", "model": "hashed-bag-of-words", "dimensions": self.dimensions}


def get_document_embedder():
    """EMBEDDING_MODE=mock -> deterministic local mock; anything else -> the
    shared real EmbeddingClient adapter (cdao/local/azure/azure_openai)."""
    settings = get_settings()
    if settings.embedding_client_mode.lower() == "mock":
        return MockEmbeddingClient(int(settings.embedding_dim))
    from app.llm.embedding_client import get_embedding_client

    return get_embedding_client()

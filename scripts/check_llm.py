"""Round C task 1.3 — prove the real LLM and real embeddings work before
building on them.

Makes ONE live Claude call through the app's own client selector and ONE live
local embedding, and asserts the embedding length equals EMBEDDING_DIM.

Run: python3 scripts/check_llm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.llm.client import get_llm_client  # noqa: E402
from app.llm.embedding_client import get_embedding_client  # noqa: E402


def main() -> int:
    settings = get_settings()
    print(f"LLM_MODE={settings.llm_client_mode}  ANTHROPIC_MODEL={settings.anthropic_model}")
    print(f"EMBEDDING_MODE={settings.embedding_client_mode}  "
          f"LOCAL_EMBEDDING_MODEL={settings.local_embedding_model}  "
          f"EMBEDDING_DIM={settings.embedding_dim}")

    llm = get_llm_client()
    print(f"\nLLM client: {llm.describe()}")
    reply = llm.generate(
        "In one sentence: what is a fee discount sharing rule in an advisor "
        "compensation plan?"
    )
    print(f"LLM reply: {reply}")
    assert reply and "mock-llm" not in reply, "expected real Claude output"

    emb = get_embedding_client()
    print(f"\nEmbedding client: {emb.describe()}")
    vector = emb.embed("managed account fee reduction above the 10% sharing threshold")
    print(f"embedding length: {len(vector)}  first 5 dims: {[round(v, 4) for v in vector[:5]]}")
    assert len(vector) == settings.embedding_dim, (
        f"embedding length {len(vector)} != EMBEDDING_DIM {settings.embedding_dim}")

    print("\nOK — live Claude call and live local embedding both verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

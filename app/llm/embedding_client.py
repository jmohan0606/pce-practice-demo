from __future__ import annotations

from typing import Protocol

from app.config.settings import get_settings


class EmbeddingClientError(RuntimeError):
    pass


class EmbeddingClient(Protocol):
    """Adapter interface for semantic text embeddings.

    Every knowledge embedding comes from a real semantic model, local or Azure,
    selected by EMBEDDING_MODE. Nothing outside the implementations below may
    import sentence_transformers or the openai SDK for embeddings.
    """

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str]) -> list[list[float]]: ...

    def describe(self) -> dict: ...


class LocalEmbeddingClient:
    """sentence-transformers model, free and fully local.

    Vectors are L2-normalized so cosine similarity in the vector store is the
    plain dot product; the same normalization the Azure embeddings API applies.
    """

    def __init__(self) -> None:
        settings = get_settings()
        # SDK import stays inside the class so mock/azure/cdao paths never load torch.
        from sentence_transformers import SentenceTransformer

        self.model_name = settings.local_embedding_model
        self._model = SentenceTransformer(self.model_name)
        self.dimensions = int(self._model.get_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False
        )
        return [vector.tolist() for vector in vectors]

    def describe(self) -> dict:
        return {"mode": "local", "model": self.model_name, "dimensions": self.dimensions}


class AzureOpenAIEmbeddingClient:
    """Azure OpenAI embeddings via JPMC's SmartSDK / Fusion gateway — the secondary
    client-site path (EMBEDDING_MODE=azure).

    Uses the SAME `smart_sdk.models.Model(provider=AZURE_OPENAI, ...)` construction as
    AzureOpenAILLMClient, but pointed at the embedding deployment. The `smart_sdk`
    import is GUARDED — imported only here, only when this mode is selected — so the
    app boots without smart_sdk in every other mode.

    Output is validated against the configured EMBEDDING_DIM so it always matches the
    graph EMBEDDING attribute DDL and the Chroma collection dimension.

    NOTE (single client-side confirmation point): the Model(...) construction below is
    the confirmed SmartSDK pattern. The exact Model→embeddings conversion symbol is not
    in the SmartSDK reference. We try the known SmartSDK conversion entry points; if
    your SmartSDK build exposes a different one, set it at the ONE marked spot below
    (`_resolve_embedder`) per your SmartSDK docs. Everything else (auth, dimension
    handling, interface) is complete and correct.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.dimensions = int(settings.embedding_dim)
        try:
            from smart_sdk.models import Model, ModelProvider  # type: ignore
        except ImportError as exc:  # pragma: no cover — client-only package
            raise EmbeddingClientError(
                "EMBEDDING_MODE=azure requires the client-only 'smart_sdk' package "
                "(JPMC artifactory). Use EMBEDDING_MODE=local here. Error: " + str(exc)
            ) from exc

        auth_method = (settings.azure_auth_method or "key").lower()
        if auth_method == "certificate":
            from smart_sdk.models import AuthMethod  # type: ignore
            model = Model(
                name=settings.azure_embedding_model_name,
                auth_method=AuthMethod.CERTIFICATE,
                provider=ModelProvider.AZURE_OPENAI,
                azure_endpoint=settings.azure_endpoint,
                azure_api_version=settings.azure_api_version,
                azure_deployment_name=settings.azure_embedding_deployment_name,
                certificate_path=settings.azure_certificate_path,
                api_key=settings.azure_api_key,
                tenant_id=settings.azure_tenant_id,
                client_id=settings.azure_client_id,
            )
        else:
            if not settings.azure_api_key or not settings.fusion_base_url:
                raise EmbeddingClientError(
                    "EMBEDDING_MODE=azure (key auth) requires AZURE_API_KEY and "
                    "FUSION_BASE_URL"
                )
            model = Model(
                name=settings.azure_embedding_model_name,
                provider=ModelProvider.AZURE_OPENAI,
                azure_deployment_name=settings.azure_embedding_deployment_name,
                api_key=settings.azure_api_key,
                azure_api_version=settings.azure_api_version,
                azure_endpoint=settings.azure_endpoint or settings.fusion_base_url,
                fusion_base_url=settings.fusion_base_url,
                fusion_workspace_id=settings.fusion_workspace_id,
                fusion_env=settings.fusion_env,
            )
        self._model = model
        self.deployment = settings.azure_embedding_deployment_name
        self._embedder = self._resolve_embedder(model)

    @staticmethod
    def _resolve_embedder(model):
        """Convert the SmartSDK Model into an embeddings object exposing embed_query /
        embed_documents. Tries the known SmartSDK entry points in order. If your SmartSDK build
        names this differently, add it to `candidates` — this is the one client-side confirm spot.
        """
        candidates = []
        try:  # most likely: an embeddings converter mirroring _to_langgraph_model
            from smart_sdk.ext.langgraph.models._models import _to_langgraph_embeddings  # type: ignore
            candidates.append(lambda: _to_langgraph_embeddings(model))
        except ImportError:
            pass
        try:
            from smart_sdk.ext.langchain.embeddings._embeddings import _to_langchain_embeddings  # type: ignore
            candidates.append(lambda: _to_langchain_embeddings(model))
        except ImportError:
            pass
        # Model may expose a direct conversion method
        candidates.append(lambda: model.to_embeddings())  # type: ignore[attr-defined]
        for build in candidates:
            try:
                embedder = build()
                if embedder is not None:
                    return embedder
            except (AttributeError, TypeError, ImportError):
                continue
        raise EmbeddingClientError(
            "Could not resolve a SmartSDK embeddings object from the Model. The Model(...) "
            "construction is confirmed; only the Model->embeddings conversion symbol needs "
            "confirming for your SmartSDK build. Set it in AzureOpenAIEmbeddingClient."
            "_resolve_embedder."
        )

    def _fit_dim(self, vector: list[float]) -> list[float]:
        """Guard: the store DDL is fixed at EMBEDDING_DIM, so surface any mismatch loudly rather
        than silently corrupting the vector space."""
        if len(vector) != self.dimensions:
            raise EmbeddingClientError(
                f"Azure embedding returned dim {len(vector)} but EMBEDDING_DIM={self.dimensions}. "
                f"Set EMBEDDING_DIM to match deployment '{self.deployment}' "
                f"(text-embedding-3-small=1536, -3-large=3072)."
            )
        return list(vector)

    def embed(self, text: str) -> list[float]:
        return self._fit_dim(list(self._embedder.embed_query(text)))

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        vectors = self._embedder.embed_documents(list(texts))
        return [self._fit_dim(list(v)) for v in vectors]

    def describe(self) -> dict:
        return {"mode": "azure", "model": f"azure-smartsdk:{self.deployment}", "dimensions": self.dimensions}


class AzureOpenAIDirectEmbeddingClient:
    """Azure OpenAI embeddings via the direct `openai` AzureOpenAI SDK (generic Azure, NOT the
    JPMC Fusion gateway) — EMBEDDING_MODE=azure_openai. Kept for environments that expose
    Azure OpenAI directly with an endpoint+key rather than through SmartSDK."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
            raise EmbeddingClientError(
                "EMBEDDING_MODE=azure_openai requires AZURE_OPENAI_ENDPOINT and "
                "AZURE_OPENAI_API_KEY in .env"
            )
        from openai import AzureOpenAI  # imported here so nothing else depends on the SDK

        self._client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        self.deployment = settings.azure_openai_embedding_deployment

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.deployment, input=list(texts))
        return [item.embedding for item in response.data]

    def describe(self) -> dict:
        return {"mode": "azure_openai", "model": f"azure:{self.deployment}"}


class CdaoOpenAIEmbeddingClient:
    """Azure OpenAI embeddings via the client's cdao SDK — the PRIMARY client-site embedding path
    (EMBEDDING_MODE=cdao / cdao_openai). Mirrors CdaoOpenAILLMClient exactly: same cdao client
    construction (shared `build_cdao_openai_client`, one PCL login serves both), standard OpenAI
    embeddings shape. The SmartSDK AzureOpenAIEmbeddingClient (mode=azure) stays as the secondary
    alternate.

    Pattern (verified live in the client notebook — a real run returned a 3072-dim vector):
        from cdao import openai_azure_client
        client = openai_azure_client(api_version=..., workspace_id=...)
        response = client.embeddings.create(model="text-embedding-3-large-1", input=<text|list>)
        vectors = [row.embedding for row in response.data]

    This is the standard `client.embeddings.create -> response.data[i].embedding` shape, so it maps
    1:1 onto the EmbeddingClient interface (embed / embed_many) — the exact return shape every
    consumer (RAG ingestion, similarity) already expects from LocalEmbeddingClient.

    DIMENSION — CRITICAL: text-embedding-3-large returns 3072-dim vectors (confirmed by the
    developer's real run). EMBEDDING_DIM must be set to 3072 when this model is active so the
    graph EMBEDDING attribute DDL and the Chroma collection use the SAME dimension — otherwise
    vector search silently breaks. _fit_dim() surfaces any mismatch loudly.

    GUARDED IMPORT: cdao is imported only inside build_cdao_openai_client, only when this mode is
    selected — the app boots normally in local/mock/claude/azure embedding modes without cdao.

    PREREQUISITE (client machine): the SAME PCL AWS login already required for the cdao LLM adapter
    (cdao authenticates from the ambient AWS session, not from code/.env). One login covers both.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.dimensions = int(settings.embedding_dim)
        # Shared cdao client builder — same construction (and guarded import) as the LLM adapter.
        from app.llm.client import LLMClientError, build_cdao_openai_client

        try:
            self._client = build_cdao_openai_client(
                api_version=settings.cdao_api_version,
                workspace_id=settings.cdao_workspace_id,
            )
        except LLMClientError as exc:
            # Re-wrap so consumers of this module only ever see EmbeddingClientError.
            raise EmbeddingClientError(str(exc)) from exc
        self.model = settings.cdao_embedding_model

    def _fit_dim(self, vector: list[float]) -> list[float]:
        """Guard: the store DDL is fixed at EMBEDDING_DIM, so surface any mismatch loudly rather
        than silently corrupting the vector space (text-embedding-3-large=3072)."""
        if len(vector) != self.dimensions:
            raise EmbeddingClientError(
                f"cdao embedding returned dim {len(vector)} but EMBEDDING_DIM={self.dimensions}. "
                f"Set EMBEDDING_DIM to match model '{self.model}' "
                f"(text-embedding-3-large=3072, -3-small=1536)."
            )
        return list(vector)

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.model, input=list(texts))
        return [self._fit_dim(list(row.embedding)) for row in response.data]

    def describe(self) -> dict:
        return {"mode": "cdao_openai", "model": f"cdao:{self.model}", "dimensions": self.dimensions}


_embedding_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """Select the EmbeddingClient per EMBEDDING_MODE:
      cdao / cdao_openai → cdao SDK Azure client (PRIMARY client-site path, confirmed-working)
      local              → sentence-transformers (fully local; build box)
      azure              → SmartSDK / Fusion gateway (secondary alternate, client site)
      azure_openai       → direct Azure OpenAI SDK (generic Azure, endpoint+key)

    Cached at module level — the local model load (~90MB) should happen once per
    process, not per request.
    """
    global _embedding_client
    if _embedding_client is not None:
        return _embedding_client
    mode = get_settings().embedding_client_mode.lower()
    if mode in ("cdao", "cdao_openai"):
        _embedding_client = CdaoOpenAIEmbeddingClient()
    elif mode == "local":
        _embedding_client = LocalEmbeddingClient()
    elif mode == "azure":
        _embedding_client = AzureOpenAIEmbeddingClient()
    elif mode == "azure_openai":
        _embedding_client = AzureOpenAIDirectEmbeddingClient()
    else:
        raise EmbeddingClientError(
            f"Unknown EMBEDDING_MODE '{mode}' "
            "(expected cdao | cdao_openai | local | azure | azure_openai)"
        )
    return _embedding_client

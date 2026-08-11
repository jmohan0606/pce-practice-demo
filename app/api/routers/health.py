from __future__ import annotations

from fastapi import APIRouter

from app.config.settings import get_settings
from app.graph.client import get_graph_client
from app.shared.logging import get_logger

_log = get_logger("app.api.health")

router = APIRouter(prefix="/api", tags=["health"])


def _vertex_counts(graph) -> tuple[dict[str, int], str | None]:
    try:
        stats = graph.statistics(kind="vertex", target_type="*")
        for item in stats.get("results", []):
            counts = item.get("counts")
            if isinstance(counts, dict):
                return {k: int(v or 0) for k, v in sorted(counts.items())}, None
        return {}, "statistics returned no counts"
    except Exception as exc:  # noqa: BLE001 — health reports, never raises
        return {}, f"{type(exc).__name__}: {exc}"


def _llm_status() -> dict:
    settings = get_settings()
    status: dict = {"mode": settings.llm_client_mode}
    try:
        from app.llm.client import get_llm_client

        client = get_llm_client()
        status.update(client.describe())
        status["reachable"] = True
    except Exception as exc:  # noqa: BLE001 — honest, never fabricated
        status["reachable"] = False
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    graph = get_graph_client()
    graph_health = graph.health()
    counts, counts_error = _vertex_counts(graph)
    llm = _llm_status()

    healthy = bool(graph_health.get("healthy")) and counts_error is None
    payload = {
        "healthy": healthy,
        "app": settings.app_name,
        "version": settings.app_version,
        "graph": {
            **graph_health,
            "client_mode": settings.graph_client_mode,
            "tier": graph_health.get("active_tier") or graph_health.get("served_by_tier")
            or (4 if graph_health.get("mode") == "mock" else None),
        },
        "llm": llm,
        "vertex_counts": counts,
    }
    if counts_error:
        payload["vertex_counts_error"] = counts_error
    if not healthy:
        _log.warning("health check unhealthy", extra={"graph": graph_health, "counts_error": counts_error})
    return payload

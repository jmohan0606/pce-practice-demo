from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.correlation import CorrelationIdMiddleware
from app.api.middleware.error_handlers import register_exception_handlers
from app.api.routers.advisor import router as advisor_router
from app.api.routers.chat import router as chat_router
from app.api.routers.dashboard import router as dashboard_router
from app.api.routers.flags import router as flags_router
from app.api.routers.documents import router as documents_router
from app.api.routers.drilldown import router as drilldown_router
from app.api.routers.export import router as export_router
from app.api.routers.glossary import router as glossary_router
from app.api.routers.nnm import router as nnm_router
from app.api.routers.noncredited import router as noncredited_router
from app.api.routers.ranking import router as ranking_router
from app.api.routers.health import router as health_router
from app.api.routers.insights import alias_router as exceptions_alias_router
from app.api.routers.insights import router as insights_router
from app.api.routers.jobs import router as jobs_router
from app.api.routers.rules import router as rules_router
from app.api.routers.trace import router as trace_router
from app.config.settings import get_settings
from app.rules.seed import ensure_v0_seed
from app.shared.logging import configure_logging, get_logger


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    # Handlers registered BEFORE CORSMiddleware is added, so the CORS-safe
    # catch-all runs inside the middleware stack (V2 Round 5 A6 lesson).
    register_exception_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    # Codespaces: the browser reaches the frontend on its forwarded HTTPS URL,
    # so that origin must be allowed alongside localhost.
    import os as _os

    _cors_origins = [
        f"http://localhost:{settings.frontend_port}",
        f"http://127.0.0.1:{settings.frontend_port}",
    ]
    _cs_name = _os.environ.get("CODESPACE_NAME")
    _cs_domain = _os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
    if _cs_name and _cs_domain:
        _cors_origins.append(
            f"https://{_cs_name}-{settings.frontend_port}.{_cs_domain}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(advisor_router)
    app.include_router(chat_router)
    app.include_router(dashboard_router)
    app.include_router(flags_router)
    app.include_router(documents_router)
    app.include_router(drilldown_router)
    app.include_router(glossary_router)
    app.include_router(nnm_router)
    app.include_router(noncredited_router)
    app.include_router(ranking_router)
    app.include_router(export_router)
    app.include_router(rules_router)
    app.include_router(insights_router)
    app.include_router(exceptions_alias_router)
    app.include_router(jobs_router)
    app.include_router(trace_router)

    # B3.7: seed rule-set v0 at first startup if no version exists (idempotent).
    ensure_v0_seed()

    log = get_logger("app.api")
    log.info("app configured", extra={"resolved_paths": settings.resolved_paths_report()})
    return app


app = create_app()

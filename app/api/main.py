from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.correlation import CorrelationIdMiddleware
from app.api.middleware.error_handlers import register_exception_handlers
from app.api.routers.dashboard import router as dashboard_router
from app.api.routers.documents import router as documents_router
from app.api.routers.health import router as health_router
from app.api.routers.insights import router as insights_router
from app.api.routers.rules import router as rules_router
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://localhost:{settings.frontend_port}",
            f"http://127.0.0.1:{settings.frontend_port}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(dashboard_router)
    app.include_router(documents_router)
    app.include_router(rules_router)
    app.include_router(insights_router)

    # B3.7: seed rule-set v0 at first startup if no version exists (idempotent).
    ensure_v0_seed()

    log = get_logger("app.api")
    log.info("app configured", extra={"resolved_paths": settings.resolved_paths_report()})
    return app


app = create_app()

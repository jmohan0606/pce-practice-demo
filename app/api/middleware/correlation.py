"""Correlation-id middleware — makes every request's logs traceable end-to-end.

For each inbound request we resolve a correlation id (reusing an inbound
``X-Correlation-ID`` / ``X-Request-ID`` header when a proxy/ALB supplies one, else
minting a fresh one), bind it to the request-scoped contextvar so every log line
emitted while handling the request carries it, and echo it back on the response
``X-Correlation-ID`` header. Request start/finish (with status + duration) is logged
at INFO; an unhandled exception is logged with a full trace and re-raised so the
registered exception handlers produce the clean client response.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.shared.correlation import get_correlation_id, new_correlation_id, set_correlation_id
from app.shared.logging import get_logger

_log = get_logger("app.request")

_INBOUND_HEADERS = ("x-correlation-id", "x-request-id")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = ""
        for header in _INBOUND_HEADERS:
            if value := request.headers.get(header):
                correlation_id = value.strip()
                break
        set_correlation_id(correlation_id or new_correlation_id())

        start = time.perf_counter()
        _log.info(
            "request start",
            extra={"method": request.method, "path": request.url.path},
        )
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            _log.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise  # handled by registered exception handlers → clean structured JSON

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Correlation-ID"] = get_correlation_id()
        _log.info(
            "request complete",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response


__all__ = ["CorrelationIdMiddleware"]

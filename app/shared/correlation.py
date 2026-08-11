"""Correlation-id propagation for request-scoped log tracing.

A single correlation id is attached to every log record emitted while handling a
request (see ``app.shared.logging.JsonFormatter``). The id is stored in a
``contextvars.ContextVar`` so it flows transparently through sync and async call
stacks without threading it through every function signature.

Lifecycle:
  * ``CorrelationIdMiddleware`` (app/api/middleware/correlation.py) reads an inbound
    ``X-Correlation-ID`` / ``X-Request-ID`` header, or mints a new id, and calls
    :func:`set_correlation_id` at the start of each request.
  * Any code (adapters, services, exception handlers) reads it via
    :func:`get_correlation_id` — no request object required.
  * The middleware echoes the id back on the response ``X-Correlation-ID`` header so
    a caller (or CloudWatch/ALB access log) can line requests up with app logs.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

# "-" means "no active request" (e.g. startup/shutdown/background logging).
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def new_correlation_id() -> str:
    """Generate a fresh, short, URL-safe correlation id."""
    return uuid.uuid4().hex


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value or "-")


def get_correlation_id() -> str:
    return _correlation_id.get()


__all__ = ["new_correlation_id", "set_correlation_id", "get_correlation_id"]

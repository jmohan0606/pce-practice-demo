"""Adapter-call logging (Section 2 adapters: GraphClient / LLMClient / etc.).

Every call into an external-boundary adapter is wrapped so that when it raises, the
failure is logged once, with structured context (component, operation, a redacted
argument summary, and the request correlation id) and a full stack trace — then the
original exception propagates so the global FastAPI exception handler can turn it
into a clean structured error response for the user (never a raw stack trace).

Two entry points:
  * ``@logged_adapter_call("graph")`` — decorator for adapter methods. The operation
    name defaults to the wrapped method's name.
  * ``adapter_call_context(component, operation, **ctx)`` — a context manager for
    ad-hoc call sites that aren't a single method.

Argument summaries are deliberately shallow and length-capped so we never dump large
payloads or secrets (e.g. full prompts, upsert record bodies, API keys) into logs.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

from app.shared.logging import get_logger

_log = get_logger("app.adapter")

_MAX_REPR = 120

F = TypeVar("F", bound=Callable[..., Any])


def _summarize(value: Any) -> str:
    """Short, safe, non-secret-leaking repr of a positional/keyword arg."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (int, float, bool)) or value is None:
        return repr(value)
    elif isinstance(value, dict):
        return f"<dict keys={sorted(value)[:8]}>"
    elif isinstance(value, (list, tuple, set)):
        return f"<{type(value).__name__} len={len(value)}>"
    else:
        text = repr(value)
    text = text.replace("\n", " ")
    return text if len(text) <= _MAX_REPR else text[:_MAX_REPR] + "…"


def logged_adapter_call(component: str, operation: str | None = None) -> Callable[[F], F]:
    """Decorate an adapter method to log-with-context on failure, then re-raise.

    ``component`` is the adapter family (e.g. "graph", "llm"); ``operation`` defaults
    to the method name. The first positional arg (``self``) is skipped in the summary.
    """

    def decorator(fn: F) -> F:
        op = operation or fn.__name__

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — log context, then propagate
                call_args = args[1:] if args else args  # drop bound ``self``
                _log.error(
                    "adapter call failed: %s.%s -> %s: %s",
                    component,
                    op,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                    extra={
                        "adapter_component": component,
                        "adapter_operation": op,
                        "adapter_args": [_summarize(a) for a in call_args],
                        "adapter_kwargs": {k: _summarize(v) for k, v in kwargs.items()},
                        "error_type": type(exc).__name__,
                    },
                )
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


@contextmanager
def adapter_call_context(component: str, operation: str, **ctx: Any) -> Iterator[None]:
    """Context-manager form for call sites that aren't a single decorated method."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001
        _log.error(
            "adapter call failed: %s.%s -> %s: %s",
            component,
            operation,
            type(exc).__name__,
            exc,
            exc_info=True,
            extra={
                "adapter_component": component,
                "adapter_operation": operation,
                "error_type": type(exc).__name__,
                **{k: _summarize(v) for k, v in ctx.items()},
            },
        )
        raise


__all__ = ["logged_adapter_call", "adapter_call_context"]

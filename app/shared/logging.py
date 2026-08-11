"""Central structured logging — production-grade, AWS CloudWatch-ready.

This module configures Python's stdlib :mod:`logging` (not loguru) so the same
structured JSON records work identically on a laptop and on ECS/Fargate. Every
record carries: ISO-8601 UTC timestamp, level, logger name, correlation/request id
(see :mod:`app.shared.correlation`), the message, and — on errors — the full
exception type, message and stack trace.

Swappable sink (config, not code) — set ``LOG_SINK`` in ``.env``:

    LOG_SINK=file        # LOCAL DEFAULT
        Structured JSON written to ``logs/app.log`` via a RotatingFileHandler
        (``LOG_ROTATE_MAX_BYTES`` per file, ``LOG_ROTATE_BACKUP_COUNT`` backups).
        Good for local dev and any host where you tail a file.

    LOG_SINK=stdout      # RECOMMENDED FOR ECS / FARGATE
        The exact same JSON, written to stdout. On Fargate the awslogs / FireLens
        log driver ships stdout straight to CloudWatch Logs, so no in-app AWS SDK
        or credentials are needed. This is the preferred CloudWatch path — set
        ``LOG_SINK=stdout`` in the task definition and point the awslogs driver at
        your log group. Nothing else changes.

    LOG_SINK=cloudwatch  # DIRECT PUSH (when stdout shipping is not available)
        Uses a `watchtower` CloudWatchLogHandler to push records directly to the
        ``LOG_CLOUDWATCH_GROUP`` log group (stream ``LOG_CLOUDWATCH_STREAM`` or an
        auto host/pid stream), using the ambient IAM role / ``AWS_REGION``. Requires
        ``pip install watchtower``; if the package or credentials are missing we log
        a warning and fall back to stdout so the app never fails to boot over logging.

Switching environments is therefore a one-line ``.env`` / task-definition change —
never a rewrite. JSON formatting is on by default (``LOG_JSON=true``); set
``LOG_JSON=false`` for a coloured human-readable console during local debugging.

Usage elsewhere::

    from app.shared.logging import get_logger
    log = get_logger(__name__)
    log.info("thing happened", extra={"advisor_id": "A001"})

The module-level ``logger`` (named ``app``) is kept for backwards compatibility.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import get_settings
from app.shared.correlation import get_correlation_id

# Standard LogRecord attributes — anything NOT in here that appears on a record was
# passed via logging's ``extra=`` and is promoted into the JSON payload.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render each LogRecord as a single-line JSON object (one event per line).

    Includes the request correlation id and, for error records, the full exception
    class/message and formatted stack trace so failures are fully diagnosable from
    the log alone (in a file or in CloudWatch).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": get_correlation_id(),
            "message": record.getMessage(),
        }
        # Locate the source for quick triage.
        payload["source"] = f"{record.module}:{record.funcName}:{record.lineno}"

        # Promote structured extras (e.g. log.info(..., extra={"advisor_id": ...})).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        # Full exception detail on errors.
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exception"] = {
                "type": getattr(exc_type, "__name__", str(exc_type)),
                "message": str(exc_value),
                "stack_trace": self.formatException(record.exc_info),
            }
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


_HUMAN_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)s | cid=%(correlation_id)s | "
    "%(module)s:%(funcName)s:%(lineno)d | %(message)s"
)


class _CorrelationFilter(logging.Filter):
    """Make ``correlation_id`` available to the human (non-JSON) formatter too."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


def _build_handler(settings) -> logging.Handler:
    sink = (settings.log_sink or "file").lower()
    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_json else logging.Formatter(_HUMAN_FORMAT)
    )

    handler: logging.Handler
    if sink == "stdout":
        handler = logging.StreamHandler(sys.stdout)
    elif sink == "cloudwatch":
        handler = _build_cloudwatch_handler(settings)
    else:  # "file" (default)
        from app.config.settings import resolve_app_path
        log_dir = resolve_app_path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / settings.log_file_name,
            maxBytes=settings.log_rotate_max_bytes,
            backupCount=settings.log_rotate_backup_count,
            encoding="utf-8",
        )

    handler.setFormatter(formatter)
    handler.addFilter(_CorrelationFilter())
    return handler


def _build_cloudwatch_handler(settings) -> logging.Handler:
    """watchtower CloudWatch handler, with a safe stdout fallback so logging config
    can never crash the app (a booting service must not die because AWS is
    misconfigured — it degrades to stdout, which Fargate still captures)."""
    try:
        import watchtower  # type: ignore

        kwargs: dict[str, object] = {"log_group": settings.log_cloudwatch_group}
        if settings.log_cloudwatch_stream:
            kwargs["log_stream_name"] = settings.log_cloudwatch_stream
        if settings.aws_region:
            import boto3  # type: ignore

            kwargs["boto3_client"] = boto3.client("logs", region_name=settings.aws_region)
        return watchtower.CloudWatchLogHandler(**kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 — never fail boot over log transport
        fallback = logging.StreamHandler(sys.stdout)
        fallback.setFormatter(JsonFormatter() if settings.log_json else logging.Formatter(_HUMAN_FORMAT))
        fallback.addFilter(_CorrelationFilter())
        logging.getLogger("app").warning(
            "LOG_SINK=cloudwatch unavailable (%s); falling back to stdout JSON", exc
        )
        return fallback


_configured = False


def configure_logging(force: bool = False) -> None:
    """Install the structured handler on the root logger. Idempotent."""
    global _configured
    if _configured and not force:
        return

    settings = get_settings()
    root = logging.getLogger()
    # Replace any prior handlers (e.g. uvicorn's default / a previous call).
    for existing in list(root.handlers):
        root.removeHandler(existing)

    root.setLevel(settings.log_level.upper())
    root.addHandler(_build_handler(settings))

    # Route uvicorn/fastapi through the same structured handler instead of their
    # own plain formatters, so every line in the file/stream is JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Preferred accessor. Ensures configuration has run before returning a logger."""
    if not _configured:
        configure_logging()
    return logging.getLogger(name or "app")


# Backwards-compatible module-level logger (was a loguru logger previously). Both
# loguru and stdlib expose .info/.warning/.error/.exception, so existing call sites
# (e.g. app/api/middleware/error_handlers.py) keep working unchanged.
logger = logging.getLogger("app")


__all__ = ["logger", "configure_logging", "get_logger", "JsonFormatter"]

"""Application logging configuration and request correlation context."""

from __future__ import annotations

import contextvars
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = r"^[A-Za-z0-9._-]{1,128}$"

request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _ContextFilter(logging.Filter):
    """Populate fields used by the formatter without recording request data."""

    def filter(self, record: logging.LogRecord) -> bool:
        _populate_safe_fields(record)
        return True


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        _populate_safe_fields(record)
        return super().format(record)


_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "event=%(event)s request_id=%(request_id)s method=%(method)s "
    "route=%(route)s status=%(status)s duration_ms=%(duration_ms)s "
    "exception_type=%(exception_type)s stack_locations=%(stack_locations)s "
    "operation=%(operation)s model=%(model)s provider_host=%(provider_host)s "
    "error_class=%(error_class)s error_category=%(error_category)s "
    "validation_category=%(validation_category)s attempt=%(attempt)s "
    "phase=%(phase)s pid=%(pid)s outcome=%(outcome)s ready=%(ready)s "
    "auth_method=%(auth_method)s email_fingerprint=%(email_fingerprint)s "
    "user_id=%(user_id)s reason_code=%(reason_code)s "
    "path=%(path)s nnue_path=%(nnue_path)s "
    "depth=%(depth)s movetime_ms=%(movetime_ms)s multipv=%(multipv)s "
    "threads=%(threads)s hash_mb=%(hash_mb)s"
)
_SAFE_FIELDS = (
    "method", "route", "status", "duration_ms", "exception_type",
    "stack_locations", "operation", "model", "provider_host",
    "error_class", "error_category", "validation_category", "attempt",
    "phase", "pid", "outcome", "ready", "auth_method", "email_fingerprint",
    "user_id", "reason_code", "path", "nnue_path", "depth", "movetime_ms",
    "multipv", "threads", "hash_mb",
)
_FIELD_LIMITS = {
    "stack_locations": 1200,
    "route": 160,
    "provider_host": 253,
    "path": 512,
    "nnue_path": 512,
}
_EVENT_NAME = re.compile(r"^[a-z0-9_.-]{1,80}$")


def _safe_scalar(value: Any, field: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (str, int, float)):
        text = str(value)
    else:
        return "-"
    text = "".join(char if char.isprintable() else "_" for char in text)
    limit = _FIELD_LIMITS.get(field, 120)
    return text[:limit] or "-"


def _populate_safe_fields(record: logging.LogRecord) -> None:
    for field in _SAFE_FIELDS:
        value = getattr(record, field, None)
        # Keep process ids numeric for structured log consumers; the formatter
        # already stringifies values when rendering text logs.
        if field == "pid" and isinstance(value, int) and not isinstance(value, bool):
            continue
        setattr(record, field, _safe_scalar(value, field))
    event = getattr(record, "event", None)
    record.event = event if isinstance(event, str) and _EVENT_NAME.fullmatch(event) else "application.event"
    record.request_id = _safe_scalar(
        getattr(record, "request_id", None) or request_id_context.get(), "request_id"
    )


_HANDLER_MARKER = "_xiangqi_owned_handler"


def configure_logging(project_root: Path | None = None) -> None:
    """Install the console and rotating API log handlers once.

    Calling this repeatedly is safe and will reuse existing owned handlers.
    The logs directory is created only when this function is called.
    """

    # logging_config.py lives at <project>/apps/api/app; the repository root
    # is therefore three parents above this file.
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[3]
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "api.log"

    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = _Formatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S%z")

    owned = [h for h in logger.handlers if getattr(h, _HANDLER_MARKER, False)]
    console = next((h for h in owned if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)), None)
    file_handler = next((h for h in owned if isinstance(h, RotatingFileHandler)), None)

    if console is None:
        console = logging.StreamHandler()
        setattr(console, _HANDLER_MARKER, True)
        logger.addHandler(console)
    console.setFormatter(formatter)
    console.addFilter(_ContextFilter()) if not any(isinstance(f, _ContextFilter) for f in console.filters) else None

    if file_handler is None or Path(getattr(file_handler, "baseFilename", "")) != log_path.resolve():
        if file_handler is not None:
            logger.removeHandler(file_handler)
            file_handler.close()
        file_handler = RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        setattr(file_handler, _HANDLER_MARKER, True)
        logger.addHandler(file_handler)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_ContextFilter()) if not any(isinstance(f, _ContextFilter) for f in file_handler.filters) else None


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the application namespace."""

    return logging.getLogger(name if name.startswith("app") else f"app.{name}")


def log_extra(**values: Any) -> dict[str, Any]:
    """Build safe structured fields for application events."""

    return values


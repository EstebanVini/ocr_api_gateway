import logging
import sys

import structlog
from asgi_correlation_id import correlation_id
from structlog.typing import EventDict, WrappedLogger

_SENSITIVE_KEYS = {"api_key", "apikey", "text", "content", "raw", "file_bytes"}


def _scrub_sensitive(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Defense-in-depth: drop sensitive keys even if a future change logs them by mistake."""
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def _add_request_id(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    request_id = correlation_id.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _scrub_sensitive,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]

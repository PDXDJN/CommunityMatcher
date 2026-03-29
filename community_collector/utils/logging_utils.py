"""Structured logging setup for the collector."""
from __future__ import annotations
import logging
import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for the collector. Call once at startup."""
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )


def get_logger(name: str | None = None):
    """Return a structlog logger, optionally bound with a name context."""
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log

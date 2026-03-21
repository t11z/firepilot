"""Structlog configuration for mcp-itsm.

Configures structured JSON logging for all tool invocations and server events.
Every tool call must produce a structured log entry per the logging contract
defined in ADR-0005.
"""

import sys

import structlog


def configure_logging() -> None:
    """Configure structlog with JSON rendering for structured audit logging.

    Logs are written to stderr so they do not corrupt the MCP stdio protocol
    stream, which exclusively owns stdout for JSONRPC message exchange.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Optional logger name for contextual identification.

    Returns:
        A configured structlog BoundLogger instance.
    """
    return structlog.get_logger(name)

"""structlog setup: JSON lines in live mode, a readable console format locally.

`configure_logging` is idempotent. Every line carries a timestamp, level and the correlation ids
bound with `log_context` (`request_id`, `job_id`, `case_id`, `run_id`), and passes through the
redaction processor last, so nothing sensitive reaches the renderer.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Literal, TextIO

import structlog
from structlog.contextvars import merge_contextvars
from structlog.types import Processor

from cso.observability.redaction import redact_event
from cso.settings import Settings, resolved_log_format

LogFormat = Literal["json", "console"]
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}

_configured: tuple[LogFormat, str] | None = None


class _StdoutLogger:
    """Writes each line to whatever `sys.stdout` is *now*, never to a stream captured earlier.

    Binding the destination at configuration time breaks when the process (or a test runner)
    later swaps and closes its stdout: every later log call would raise on a closed file.
    """

    def msg(self, message: str) -> None:
        print(message, file=sys.stdout, flush=True)

    log = debug = info = warn = warning = err = error = critical = exception = fatal = msg
    failure = msg


class _StdoutLoggerFactory:
    def __call__(self, *args: Any) -> _StdoutLogger:
        return _StdoutLogger()


def build_processors(fmt: LogFormat) -> list[Processor]:
    """The processor chain: context, level, time, exception text, redaction, renderer."""
    renderer: Processor = (
        structlog.processors.JSONRenderer(sort_keys=True)
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    return [
        merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_event,
        renderer,
    ]


def configure_logging(
    *,
    fmt: LogFormat = "console",
    level: str = "INFO",
    stream: TextIO | None = None,
    force: bool = False,
) -> None:
    """Configure structlog once; later calls with the same settings do nothing.

    `stream` and `force` exist for tests, which capture output in a buffer.
    """
    global _configured
    if _configured == (fmt, level) and not force and stream is None:
        return
    structlog.configure(
        processors=build_processors(fmt),
        wrapper_class=structlog.make_filtering_bound_logger(_LEVELS.get(level.upper(), 20)),
        logger_factory=(
            structlog.PrintLoggerFactory(file=stream) if stream else _StdoutLoggerFactory()
        ),
        cache_logger_on_first_use=False,
    )
    logging.getLogger("uvicorn.access").disabled = True  # replaced by the access line
    _configured = (fmt, level)


def configure_from_settings(settings: Settings, *, stream: TextIO | None = None) -> None:
    """Configure logging from the process settings (called at startup)."""
    configure_logging(fmt=resolved_log_format(settings), level=settings.log_level, stream=stream)


def get_logger(name: str | None = None, **bind: Any) -> Any:
    """A structlog logger, optionally bound with fixed fields."""
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return logger.bind(**bind) if bind else logger

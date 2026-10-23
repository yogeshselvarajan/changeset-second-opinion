"""Log correlation ids carried in contextvars (request, job, case, run)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from structlog.contextvars import bound_contextvars, clear_contextvars

CONTEXT_KEYS = ("request_id", "job_id", "case_id", "run_id")


@contextmanager
def log_context(**values: Any) -> Iterator[None]:
    """Bind correlation ids for the duration of a block; `None` values are skipped.

    Every log line emitted inside the block (by any logger) carries these keys, and the previous
    values are restored on exit, so nested work such as a worker step inside a job is safe.
    """
    bound = {k: str(v) for k, v in values.items() if v is not None}
    with bound_contextvars(**bound):
        yield


def current_context() -> dict[str, Any]:
    """The correlation ids bound right now (for tests and diagnostics)."""
    return {k: v for k, v in structlog.contextvars.get_contextvars().items() if k in CONTEXT_KEYS}


def reset_context() -> None:
    """Drop every bound id (used when a task starts or in tests)."""
    clear_contextvars()

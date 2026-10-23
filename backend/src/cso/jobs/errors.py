"""Job failures and how they are classified into retry or terminal failure.

Transient failures (upstream down, timeouts, unexpected crashes) retry with backoff until the
attempts are used up. Permanent ones (bad input, schema deviations, renderer bugs) fail at once. The
stored error is only the short code; details go to the log, never into the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from cso.adapters.decider.errors import (
    DeciderBusy,
    DeciderError,
    DeciderSchemaError,
    DeciderStateTooLong,
    DeciderUnavailable,
)
from cso.adapters.osm.errors import (
    BandwidthLimitError,
    NotAllowedError,
    NotFoundError,
    OsmError,
    OsmTimeoutError,
    ParseError,
    Redacted403,
    TooLargeError,
    UpstreamError,
)


class JobError(Exception):
    """A failure with a stable short `code`."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class TransientJobError(JobError):
    """Worth retrying later."""


class PermanentJobError(JobError):
    """Retrying cannot help."""


class JobCancelled(Exception):
    """The job's cancel flag was seen between steps."""


class LeaseLost(Exception):
    """This worker no longer owns the job (its lease expired and the job moved on)."""


@dataclass(frozen=True)
class Classified:
    """What to do about a failure."""

    retry: bool
    code: str
    detail: str


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def classify(exc: BaseException) -> Classified:
    """Map an exception to retry-or-fail plus a short code."""
    detail = _short(exc)
    if isinstance(exc, JobError):
        return Classified(isinstance(exc, TransientJobError), exc.code, exc.detail or detail)
    if isinstance(exc, DeciderError):
        transient = isinstance(exc, DeciderUnavailable | DeciderBusy)
        return Classified(transient, exc.failure_code, detail)
    if isinstance(exc, OsmError):
        return _classify_osm(exc, detail)
    if isinstance(exc, TimeoutError):
        return Classified(True, "job_timeout", detail)
    return Classified(True, "internal_error", detail)


def _classify_osm(exc: OsmError, detail: str) -> Classified:
    if isinstance(exc, NotFoundError):
        return Classified(False, "osm_not_found", detail)
    if isinstance(exc, NotAllowedError):
        return Classified(False, "osm_not_allowed", detail)
    if isinstance(exc, Redacted403):
        return Classified(False, "osm_forbidden", detail)
    if isinstance(exc, TooLargeError | ParseError):
        return Classified(False, "osm_unreadable", detail)
    if isinstance(exc, BandwidthLimitError):
        return Classified(True, "osm_bandwidth_limit", detail)
    if isinstance(exc, UpstreamError | OsmTimeoutError):
        return Classified(True, "osm_unavailable", detail)
    return Classified(True, "osm_error", detail)


def is_permanent_decider_error(exc: DeciderError) -> bool:
    """Schema deviations, state-too-long and a missing Decider are not weather: no retry."""
    return isinstance(exc, DeciderSchemaError | DeciderStateTooLong) or bool(
        getattr(exc, "permanent", False)
    )

"""Typed Decider failures. `failure_code` is what a run records as its failure reason."""

from __future__ import annotations


class DeciderError(Exception):
    """Base class; never carries a default answer."""

    failure_code = "decider_unavailable"


class DeciderUnavailable(DeciderError):
    """Connection failure or an unexpected HTTP status; the job may be retried."""

    failure_code = "decider_unavailable"


class DeciderTimeout(DeciderUnavailable):
    """The request exceeded its timeout (45 s GPU / 90 s CPU); not retried inside the client."""


class DeciderBusy(DeciderError):
    """The bounded queue was full and this request was the oldest waiter; retry the job later."""

    failure_code = "decider_busy"


class DeciderStateTooLong(DeciderError):
    """HTTP 422: the rendered state was rejected. A renderer bug; never retried."""

    failure_code = "state_too_long"


class DeciderSchemaError(DeciderError):
    """The response deviated from the contract. `raw` keeps it for debugging."""

    failure_code = "schema"

    def __init__(self, reason: str, raw: object = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw

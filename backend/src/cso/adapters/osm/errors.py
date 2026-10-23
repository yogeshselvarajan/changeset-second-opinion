"""Typed errors raised by the OSM adapter. Callers (collect) map these to coverage gaps.

Hierarchy (all derive from OsmError):
    NotAllowedError        non-GET method, off-allowlist host/scheme, or off-list redirect
    NotFoundError          404/410, or a replay key with no data
    Redacted403            403: element version redacted / user profile not public
    OsmTimeoutError        per-call timeout (8 s) or a replay __timeout__ marker
    RateLimitedError       429 after retries were exhausted
    BandwidthLimitError    509: the stage must stop, do not retry
    UpstreamError          other 4xx/5xx, network failure (status may be None)
    TooLargeError          response above the byte cap
      ElementCapExceededError  osmChange has more elements than the cap (carries limit)
    ParseError             invalid JSON/XML or an unexpected shape
      XmlSafetyError       DTD/entity/external-reference XML (billion laughs and friends)
"""

from __future__ import annotations


class OsmError(Exception):
    """Base class for every error raised by cso.adapters.osm."""


class NotAllowedError(OsmError):
    """Request refused: not GET, host/scheme off the allowlist, or a redirect off the list."""


class NotFoundError(OsmError):
    """The resource does not exist (HTTP 404/410)."""


class Redacted403(OsmError):
    """HTTP 403: the resource is redacted or not publicly readable."""


class OsmTimeoutError(OsmError):
    """The call exceeded its timeout."""


class UpstreamError(OsmError):
    """Unexpected HTTP status or transport failure."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RateLimitedError(UpstreamError):
    """HTTP 429 persisted after all retries."""


class BandwidthLimitError(UpstreamError):
    """HTTP 509: the API asks clients to stop; callers abort the stage."""


class TooLargeError(OsmError):
    """Response body exceeded the configured cap."""

    def __init__(self, message: str, *, limit: int) -> None:
        super().__init__(message)
        self.limit = limit


class ElementCapExceededError(TooLargeError):
    """osmChange holds more than the allowed number of elements (limit is the cap)."""


class ParseError(OsmError):
    """Malformed JSON/XML or a response whose shape is not what the endpoint documents."""


class XmlSafetyError(ParseError):
    """XML rejected for safety: DTD, entity declarations or external references."""

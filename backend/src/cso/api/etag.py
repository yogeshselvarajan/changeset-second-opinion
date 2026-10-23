"""Weak ETags over the case `outcome_version` for `PUT /cases/{id}/outcome` (If-Match)."""

from __future__ import annotations

import re

from cso.api.problems import InvalidParameterError, PreconditionRequiredError

_IF_MATCH = re.compile(r'^(?:W/)?"(\d{1,9})"$')


def format_etag(outcome_version: int) -> str:
    """Weak validator for an outcome version, for example `W/"3"`."""
    if outcome_version < 0:
        raise ValueError("outcome_version is never negative")
    return f'W/"{outcome_version}"'


def parse_if_match(header: str | None) -> int:
    """Outcome version from an If-Match header: 428 when absent, 400 when malformed."""
    if header is None:
        raise PreconditionRequiredError("Send If-Match with the outcome_version you last saw.")
    match = _IF_MATCH.fullmatch(header.strip())
    if match is None:
        raise InvalidParameterError('If-Match is malformed. Expected W/"<outcome_version>".')
    return int(match.group(1))

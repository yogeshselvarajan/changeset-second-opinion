"""If-Match handling for the outcome endpoint."""

from __future__ import annotations

import pytest

from cso.api.etag import format_etag, parse_if_match
from cso.api.problems import InvalidParameterError, PreconditionRequiredError


@pytest.mark.parametrize("version", [0, 1, 42, 999_999_999])
def test_round_trip(version: int) -> None:
    assert parse_if_match(format_etag(version)) == version


def test_format_is_weak_validator() -> None:
    assert format_etag(3) == 'W/"3"'


def test_negative_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        format_etag(-1)


def test_missing_header_is_428() -> None:
    with pytest.raises(PreconditionRequiredError) as caught:
        parse_if_match(None)
    assert caught.value.status == 428


@pytest.mark.parametrize(
    "header", ["", "3", "W/3", 'W/"x"', 'W/"-1"', 'W/"1234567890"', '"3" "4"', "*"]
)
def test_malformed_header_is_400(header: str) -> None:
    with pytest.raises(InvalidParameterError):
        parse_if_match(header)


def test_strong_validator_and_whitespace_are_accepted() -> None:
    assert parse_if_match('"7"') == 7
    assert parse_if_match('  W/"7" ') == 7

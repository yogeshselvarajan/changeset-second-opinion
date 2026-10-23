"""Keyset cursors: round trip, tamper rejection, limits and page building."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from cso.api.pagination import (
    DEFAULT_LIMIT,
    MAX_CURSOR_LENGTH,
    MAX_LIMIT,
    Cursor,
    _checksum,
    build_page,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)
from cso.api.problems import InvalidCursorError

WHEN = datetime(2026, 10, 17, 12, 30, 45, 123456, tzinfo=UTC)


def forge(payload: object) -> str:
    """A cursor with a correct checksum around an arbitrary payload."""
    text = json.dumps(payload, separators=(",", ":"))
    raw = f"{_checksum(text)}.{text}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize("rank", [None, 0, 3])
def test_round_trip(rank: int | None) -> None:
    cursor = Cursor(created_at=WHEN, id=uuid4(), rank=rank)
    token = encode_cursor(cursor)
    assert decode_cursor(token) == cursor
    assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert len(token) <= MAX_CURSOR_LENGTH


def test_round_trip_keeps_microseconds_and_offset() -> None:
    zone = timezone(timedelta(hours=5, minutes=30))
    cursor = Cursor(created_at=WHEN.astimezone(zone), id=uuid4())
    decoded = decode_cursor(encode_cursor(cursor))
    assert decoded.created_at == cursor.created_at
    assert decoded.created_at.microsecond == 123456


def test_encode_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone"):
        encode_cursor(Cursor(created_at=datetime(2026, 1, 1), id=uuid4()))


def test_edited_cursor_is_rejected() -> None:
    token = encode_cursor(Cursor(created_at=WHEN, id=uuid4(), rank=1))
    middle = len(token) // 2
    swapped = "A" if token[middle] != "A" else "B"
    for tampered in (token[:middle] + swapped + token[middle + 1 :], token[:-8], token + "AAAA"):
        with pytest.raises(InvalidCursorError):
            decode_cursor(tampered)


@pytest.mark.parametrize(
    "token",
    ["", "!!!", "not a cursor", "a" * (MAX_CURSOR_LENGTH + 1), "AAAA", "e30", "bnVsbA"],
)
def test_garbage_is_rejected(token: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(token)


@pytest.mark.parametrize(
    "payload",
    [
        [2, None, WHEN.isoformat(), str(uuid4())],  # unknown version
        [1, "3", WHEN.isoformat(), str(uuid4())],  # rank as text
        [1, True, WHEN.isoformat(), str(uuid4())],  # rank as bool
        [1, None, "2026-10-17T12:00:00", str(uuid4())],  # naive timestamp
        [1, None, "yesterday", str(uuid4())],  # not a timestamp
        [1, None, WHEN.isoformat(), "not-a-uuid"],  # bad id
        [1, None, WHEN.isoformat()],  # missing field
        {"c": WHEN.isoformat()},  # wrong shape
    ],
)
def test_well_signed_but_invalid_payloads_are_rejected(payload: object) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(forge(payload))


def test_invalid_cursor_is_a_400_problem() -> None:
    with pytest.raises(InvalidCursorError) as caught:
        decode_cursor("zzz")
    assert caught.value.status == 400
    assert caught.value.code == "invalid_cursor"


def test_forged_valid_payload_decodes() -> None:
    row_id = uuid4()
    cursor = decode_cursor(forge([1, 2, WHEN.isoformat(), str(row_id)]))
    assert cursor == Cursor(created_at=WHEN, id=row_id, rank=2)
    assert isinstance(cursor.id, UUID)


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(None, DEFAULT_LIMIT), (1, 1), (50, 50), (100, MAX_LIMIT), (101, MAX_LIMIT), (0, 1), (-5, 1)],
)
def test_clamp_limit(limit: int | None, expected: int) -> None:
    assert clamp_limit(limit) == expected


def test_contract_limits() -> None:
    assert (DEFAULT_LIMIT, MAX_LIMIT) == (50, 100)


def _cursor_of(row: tuple[int, datetime, UUID]) -> Cursor:
    return Cursor(created_at=row[1], id=row[2], rank=row[0])


def test_build_page_last_page_has_no_cursor() -> None:
    rows = [(i, WHEN - timedelta(minutes=i), uuid4()) for i in range(3)]
    page, token = build_page(rows, 3, _cursor_of)
    assert page == rows
    assert token is None
    assert build_page([], 3, _cursor_of) == ([], None)


def test_build_page_points_at_last_returned_row() -> None:
    rows = [(i, WHEN - timedelta(minutes=i), uuid4()) for i in range(4)]
    page, token = build_page(rows, 3, _cursor_of)
    assert page == rows[:3]
    assert token is not None
    assert decode_cursor(token) == _cursor_of(rows[2])


def test_keyset_walk_is_stable_when_rows_are_inserted_between_pages() -> None:
    # Rows ordered by created_at descending; a new newest row appears after page one.
    def row(minute: int) -> tuple[int, datetime, UUID]:
        return (0, WHEN - timedelta(minutes=minute), uuid4())

    table = sorted((row(m) for m in range(1, 8)), key=lambda r: (-r[1].timestamp(), str(r[2])))

    def fetch(after: Cursor | None, limit: int) -> list[tuple[int, datetime, UUID]]:
        rows = [
            r
            for r in table
            if after is None or (r[1], str(r[2])) < (after.created_at, str(after.id))
        ]
        return rows[: limit + 1]

    first, token = build_page(fetch(None, 3), 3, _cursor_of)
    assert token is not None
    table.insert(0, (0, WHEN + timedelta(minutes=5), uuid4()))  # newer row arrives
    second, token2 = build_page(fetch(decode_cursor(token), 3), 3, _cursor_of)
    third, token3 = (
        build_page(fetch(decode_cursor(token2 or ""), 3), 3, _cursor_of) if token2 else ([], None)
    )

    seen = [r[2] for r in first + second + third]
    assert len(seen) == len(set(seen)) == 7  # no duplicates and no skipped rows
    assert token3 is None

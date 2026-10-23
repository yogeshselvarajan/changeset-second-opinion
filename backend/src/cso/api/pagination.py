"""Keyset pagination: opaque cursors over `(created_at, id)`, with an optional lane rank.

`GET /cases` orders by `(lane_rank, created_at desc, id)`, so its cursor also carries the rank of
the last row. Other lists leave `rank` empty. A short checksum detects a cursor that was
truncated or edited by hand; cursors are position markers, not secrets.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from cso.api.problems import InvalidCursorError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_CURSOR_LENGTH = 256

_CURSOR_VERSION = 1
_TOKEN_CHARS = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Cursor:
    """Position of the last row of a page."""

    created_at: datetime
    id: UUID
    rank: int | None = None


def clamp_limit(limit: int | None) -> int:
    """Default 50 when absent, otherwise bounded to 1..100."""
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def _checksum(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def encode_cursor(cursor: Cursor) -> str:
    """URL-safe token for a cursor (no padding)."""
    if cursor.created_at.tzinfo is None:
        raise ValueError("cursor timestamps need a timezone")
    payload = json.dumps(
        [_CURSOR_VERSION, cursor.rank, cursor.created_at.isoformat(), str(cursor.id)],
        separators=(",", ":"),
    )
    raw = f"{_checksum(payload)}.{payload}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _invalid() -> InvalidCursorError:
    return InvalidCursorError("The cursor is not valid. Start again without a cursor.")


def decode_cursor(token: str) -> Cursor:
    """Parse a cursor token; a malformed, altered or oversized token raises `InvalidCursorError`."""
    if not token or len(token) > MAX_CURSOR_LENGTH or not _TOKEN_CHARS.fullmatch(token):
        raise _invalid()
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        checksum, _, payload = raw.partition(".")
        if checksum != _checksum(payload):
            raise _invalid()
        version, rank, created_at, row_id = json.loads(payload)
        if version != _CURSOR_VERSION:
            raise _invalid()
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)):
            raise _invalid()
        timestamp = datetime.fromisoformat(created_at)
        if timestamp.tzinfo is None:
            raise _invalid()
        return Cursor(created_at=timestamp, id=UUID(row_id), rank=rank)
    except InvalidCursorError:
        raise
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise _invalid() from exc


def build_page[T](
    rows: Sequence[T], limit: int, cursor_of: Callable[[T], Cursor]
) -> tuple[list[T], str | None]:
    """Split `limit + 1` fetched rows into a page and the `next_cursor` (None on the last page)."""
    if len(rows) <= limit:
        return list(rows), None
    page = list(rows[:limit])
    return page, encode_cursor(cursor_of(page[-1]))

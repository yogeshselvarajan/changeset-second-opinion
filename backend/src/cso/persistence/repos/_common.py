"""Small helpers shared by the repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from cso.persistence.tables import utcnow

__all__ = ["KeysetCursor", "like_escape", "rowcount", "utcnow"]


@dataclass(frozen=True)
class KeysetCursor:
    """Position of the last row of a page: optional lane rank, creation time, id."""

    created_at: datetime
    id: UUID
    rank: int | None = None


def like_escape(text: str) -> str:
    """Escape LIKE wildcards (use with `escape="\\\\"`)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def rowcount(session: AsyncSession, statement: Any) -> int:
    """Execute a DML statement and return the number of affected rows."""
    result = cast("CursorResult[Any]", await session.execute(statement))
    return int(result.rowcount)

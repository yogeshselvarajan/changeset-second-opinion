"""Audit events: append-only; ids are monotonic integers so `id` doubles as the keyset cursor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.persistence.repos._common import utcnow
from cso.persistence.tables import AuditEventRow


@dataclass(frozen=True)
class AuditPage:
    """One page of audit events, oldest first, and the id to continue after."""

    items: list[AuditEventRow]
    next_after_id: int | None


class AuditRepo:
    """Insert and read audit events; there is no update path."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(
        self,
        *,
        actor: str,
        action: str,
        payload: dict[str, Any] | None = None,
        case_id: UUID | None = None,
        session_id: UUID | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> AuditEventRow:
        """Record one event."""
        row = AuditEventRow(
            case_id=case_id,
            session_id=session_id,
            actor=actor,
            action=action,
            payload=payload or {},
            request_id=request_id,
            created_at=now or utcnow(),
        )
        self._s.add(row)
        await self._s.flush()
        return row

    async def list_for_case(
        self, case_id: UUID, *, after_id: int | None = None, limit: int = 50
    ) -> AuditPage:
        """Events of a case in order of occurrence, `limit` per page."""
        stmt = sa.select(AuditEventRow).where(AuditEventRow.case_id == case_id)
        if after_id is not None:
            stmt = stmt.where(AuditEventRow.id > after_id)
        rows = list(
            (await self._s.execute(stmt.order_by(AuditEventRow.id).limit(limit + 1))).scalars()
        )
        next_after: int | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_after = rows[-1].id
        return AuditPage(items=rows, next_after_id=next_after)

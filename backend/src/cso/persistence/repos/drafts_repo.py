"""Drafts: append-only comment candidates; a human always edits and posts them."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.enums import Response
from cso.domain.models import Draft
from cso.persistence.repos._common import utcnow
from cso.persistence.tables import DraftRow


def draft_to_model(row: DraftRow) -> Draft:
    """Rebuild the domain draft from its stored row."""
    return Draft.model_validate(
        {
            "id": row.id,
            "run_id": row.run_id,
            "response_type": row.response_type,
            "status": row.status,
            "model_id": row.model_id,
            "greeting": row.greeting,
            "body": row.body,
            "closing": row.closing,
            "cited_evidence_ids": row.cited_evidence_ids,
            "validation": row.validation,
            "config_version": row.config_version,
            "created_at": row.created_at,
        }
    )


class DraftsRepo:
    """Insert and read drafts; there is no update path."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(
        self,
        case_id: UUID,
        draft: Draft,
        *,
        config_version: str,
        prompt_version: str | None = None,
        usage: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> UUID:
        """Store a draft for its run. `draft.run_id` is required."""
        if draft.run_id is None:
            raise ValueError("a draft must reference the run it belongs to")
        dump = draft.model_dump(mode="json")
        row = DraftRow(
            id=draft.id or uuid4(),
            case_id=case_id,
            run_id=draft.run_id,
            response_type=draft.response_type.value,
            status=draft.status.value,
            model_id=draft.model_id,
            greeting=draft.greeting,
            body=draft.body,
            closing=draft.closing,
            cited_evidence_ids=dump["cited_evidence_ids"],
            validation=dump["validation"],
            prompt_version=prompt_version,
            config_version=config_version,
            usage=usage or {},
            created_at=now or draft.created_at or utcnow(),
        )
        self._s.add(row)
        await self._s.flush()
        return row.id

    async def get(self, draft_id: UUID) -> Draft | None:
        """The draft with this id, if any."""
        row = await self._s.get(DraftRow, draft_id)
        return None if row is None else draft_to_model(row)

    async def latest_for_run(self, run_id: UUID, response_type: Response) -> Draft | None:
        """Newest draft of this response type for the run."""
        result = await self._s.execute(
            sa.select(DraftRow)
            .where(DraftRow.run_id == run_id, DraftRow.response_type == response_type.value)
            .order_by(DraftRow.created_at.desc(), DraftRow.id)
            .limit(1)
        )
        row = result.scalars().first()
        return None if row is None else draft_to_model(row)

    async def list_for_case(self, case_id: UUID) -> list[Draft]:
        """Drafts of a case, newest first."""
        result = await self._s.execute(
            sa.select(DraftRow)
            .where(DraftRow.case_id == case_id)
            .order_by(DraftRow.created_at.desc(), DraftRow.id)
        )
        return [draft_to_model(r) for r in result.scalars()]

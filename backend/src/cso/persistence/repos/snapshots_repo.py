"""Evidence snapshots: append-only, idempotent per (case, evidence_version)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.models import EvidenceSnapshot
from cso.persistence.repos._common import utcnow
from cso.persistence.tables import EvidenceSnapshotRow


def snapshot_to_model(row: EvidenceSnapshotRow) -> EvidenceSnapshot:
    """Rebuild the domain snapshot from its stored row."""
    raw: dict[str, Any] = row.raw
    return EvidenceSnapshot.model_validate(
        {
            "id": row.id,
            "case_id": row.case_id,
            "evidence_version": row.evidence_version,
            "source": row.source,
            "fetched_at": row.fetched_at,
            "provisional": row.provisional,
            "changeset": raw["changeset"],
            "user": raw.get("user"),
            "coverage": row.coverage,
            "elements": row.elements,
            "tag_diffs": row.tag_diffs,
            "discussion": row.discussion,
            "flags": raw.get("flags", []),
            "element_counts": raw.get("element_counts", {}),
            "rendered_text": row.rendered_text,
            "rendered_tokens": row.rendered_tokens,
        }
    )


class SnapshotsRepo:
    """Insert and read snapshots; there is no update path."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(
        self, case_id: UUID, snapshot: EvidenceSnapshot, *, now: datetime | None = None
    ) -> tuple[UUID, bool]:
        """Store the snapshot unless this (case, evidence_version) exists; returns (id, created)."""
        existing = await self._s.execute(
            sa.select(EvidenceSnapshotRow.id).where(
                EvidenceSnapshotRow.case_id == case_id,
                EvidenceSnapshotRow.evidence_version == snapshot.evidence_version,
            )
        )
        found = existing.scalars().first()
        if found is not None:
            return found, False
        dump = snapshot.model_dump(mode="json")
        row = EvidenceSnapshotRow(
            id=snapshot.id or None,
            case_id=case_id,
            evidence_version=snapshot.evidence_version,
            source=snapshot.source.value,
            provisional=snapshot.provisional,
            fetched_at=snapshot.fetched_at,
            coverage=dump["coverage"],
            raw={
                "changeset": dump["changeset"],
                "user": dump["user"],
                "flags": dump["flags"],
                "element_counts": dump["element_counts"],
            },
            elements=dump["elements"],
            tag_diffs=dump["tag_diffs"],
            discussion=dump["discussion"],
            rendered_text=snapshot.rendered_text,
            rendered_tokens=snapshot.rendered_tokens,
            created_at=now or utcnow(),
        )
        self._s.add(row)
        await self._s.flush()
        return row.id, True

    async def get(self, snapshot_id: UUID) -> EvidenceSnapshot | None:
        """The snapshot with this id, if any."""
        row = await self._s.get(EvidenceSnapshotRow, snapshot_id)
        return None if row is None else snapshot_to_model(row)

    async def latest_for_case(self, case_id: UUID) -> EvidenceSnapshot | None:
        """Most recently stored snapshot of the case."""
        result = await self._s.execute(
            sa.select(EvidenceSnapshotRow)
            .where(EvidenceSnapshotRow.case_id == case_id)
            .order_by(EvidenceSnapshotRow.created_at.desc(), EvidenceSnapshotRow.id)
            .limit(1)
        )
        row = result.scalars().first()
        return None if row is None else snapshot_to_model(row)

    async def get_by_version(self, case_id: UUID, evidence_version: str) -> EvidenceSnapshot | None:
        """The snapshot of this case with this evidence version."""
        result = await self._s.execute(
            sa.select(EvidenceSnapshotRow).where(
                EvidenceSnapshotRow.case_id == case_id,
                EvidenceSnapshotRow.evidence_version == evidence_version,
            )
        )
        row = result.scalars().first()
        return None if row is None else snapshot_to_model(row)

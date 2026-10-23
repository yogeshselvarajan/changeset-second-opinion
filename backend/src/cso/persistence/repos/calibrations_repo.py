"""Applied calibrations: immutable rows that name the thresholds a configuration version carries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.persistence.repos._common import utcnow
from cso.persistence.tables import CalibrationRow


class CalibrationsRepo:
    """Insert and read calibrations. Nothing is ever updated or deleted."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(
        self,
        *,
        calibration_id: str,
        pack_id: str,
        n_outcomes: int,
        thresholds: dict[str, Any],
        band_report: list[Any],
        created_by: str,
        now: datetime | None = None,
    ) -> CalibrationRow:
        """Store one applied calibration."""
        row = CalibrationRow(
            id=calibration_id,
            pack_id=pack_id,
            created_at=now or utcnow(),
            n_outcomes=n_outcomes,
            thresholds=thresholds,
            band_report=band_report,
            created_by=created_by,
        )
        self._s.add(row)
        await self._s.flush()
        return row

    async def get(self, calibration_id: str) -> CalibrationRow | None:
        """One calibration by id."""
        return await self._s.get(CalibrationRow, calibration_id)

    async def list_for_pack(self, pack_id: str) -> list[CalibrationRow]:
        """A pack's calibrations, newest first."""
        result = await self._s.execute(
            sa.select(CalibrationRow)
            .where(CalibrationRow.pack_id == pack_id)
            .order_by(CalibrationRow.created_at.desc(), CalibrationRow.id)
        )
        return list(result.scalars())

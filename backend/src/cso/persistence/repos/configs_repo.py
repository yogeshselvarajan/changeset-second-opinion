"""Community configuration versions (content-addressed by sha256 of the canonical YAML)."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.config import CommunityConfig
from cso.persistence.errors import NotFoundError
from cso.persistence.repos._common import utcnow
from cso.persistence.tables import CommunityConfigRow


class ConfigsRepo:
    """Stores config versions; `version` is the primary key, only `is_active` ever changes."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add_if_absent(
        self,
        config: CommunityConfig,
        yaml_text: str,
        *,
        activate: bool = False,
        now: datetime | None = None,
    ) -> CommunityConfigRow:
        """Insert this version unless it exists; optionally make it the active one."""
        row = await self._s.get(CommunityConfigRow, config.version)
        if row is None:
            row = CommunityConfigRow(
                version=config.version,
                yaml=yaml_text,
                created_at=now or utcnow(),
                is_active=False,
                pack_id=config.pack_id,
                calibration_id=config.calibration.id if config.calibration else None,
            )
            self._s.add(row)
            await self._s.flush()
        if activate:
            await self.activate(config.version)
        return row

    async def get(self, version: str) -> CommunityConfigRow | None:
        """The stored row for `version`, if any."""
        return await self._s.get(CommunityConfigRow, version)

    async def list_versions(self) -> list[CommunityConfigRow]:
        """All versions, newest first."""
        result = await self._s.execute(
            sa.select(CommunityConfigRow).order_by(
                CommunityConfigRow.created_at.desc(), CommunityConfigRow.version
            )
        )
        return list(result.scalars())

    async def get_active(self) -> CommunityConfigRow | None:
        """The active version, if one is set."""
        result = await self._s.execute(
            sa.select(CommunityConfigRow).where(CommunityConfigRow.is_active.is_(True))
        )
        return result.scalars().first()

    async def activate(self, version: str) -> None:
        """Make `version` the only active configuration."""
        if await self._s.get(CommunityConfigRow, version) is None:
            raise NotFoundError(f"community config {version} is not stored")
        await self._s.execute(
            sa.update(CommunityConfigRow)
            .where(CommunityConfigRow.is_active.is_(True), CommunityConfigRow.version != version)
            .values(is_active=False)
        )
        await self._s.execute(
            sa.update(CommunityConfigRow)
            .where(CommunityConfigRow.version == version)
            .values(is_active=True)
        )
        # Bulk UPDATEs bypass the identity map; reload so cached rows show the new flags.
        for stored in await self.list_versions():
            await self._s.refresh(stored)

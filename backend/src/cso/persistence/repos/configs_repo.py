"""Community configuration versions (content-addressed by sha256 of the canonical YAML)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
        """Insert this version unless it exists; optionally make it the active one.

        Safe against concurrent callers (two workers starting together, or an API process and a
        worker): the insert is `ON CONFLICT DO NOTHING`, so a lost race leaves the winner's row
        untouched (stored configs are immutable) and the row is then read back.
        """
        row = await self._s.get(CommunityConfigRow, config.version)
        if row is None:
            values: dict[str, Any] = {
                "version": config.version,
                "yaml": yaml_text,
                "created_at": now or utcnow(),
                "is_active": False,
                "pack_id": config.pack_id,
                "calibration_id": config.calibration.id if config.calibration else None,
            }
            await self._insert_ignoring_conflict(values)
            row = await self._s.get(CommunityConfigRow, config.version)
            if row is None:  # pragma: no cover - the insert or the winner's row must be visible
                raise NotFoundError(f"community config {config.version} could not be stored")
        if activate:
            await self.activate(config.version)
        return row

    async def _insert_ignoring_conflict(self, values: dict[str, Any]) -> None:
        """INSERT the row; a row with the same primary key already present is left as it is."""
        dialect = self._s.get_bind().dialect.name
        if dialect == "sqlite":
            stmt: Any = sqlite_insert(CommunityConfigRow).values(**values).on_conflict_do_nothing()
        elif dialect == "postgresql":
            stmt = pg_insert(CommunityConfigRow).values(**values).on_conflict_do_nothing()
        else:  # pragma: no cover - other dialects are not supported by the app
            try:
                async with self._s.begin_nested():
                    self._s.add(CommunityConfigRow(**values))
                    await self._s.flush()
            except sa.exc.IntegrityError:
                pass
            return
        await self._s.execute(stmt)

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

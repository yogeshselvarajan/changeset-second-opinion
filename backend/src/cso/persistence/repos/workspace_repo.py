"""The workspace row and the invite list an admin manages. Never commits."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.workspace import (
    DEFAULT_ACCENT,
    DEFAULT_NAME,
    DEFAULT_PARAGRAPH,
    DEFAULT_SLUG,
    DEFAULT_TAGLINE,
    DEFAULT_WORKSPACE_ID,
)
from cso.persistence.repos._common import rowcount, utcnow
from cso.persistence.tables import InviteCodeRow, SessionRow, WorkspaceRow

EDITABLE = (
    "name",
    "tagline",
    "accent_hex",
    "logo_svg",
    "community_paragraph",
    "osm_signin_enabled",
)


class WorkspaceVersionConflict(Exception):
    """The settings changed since the caller read them."""

    def __init__(self, current: int) -> None:
        super().__init__(f"workspace is at version {current}")
        self.current = current


class WorkspaceRepo:
    """Storage for the single workspace and for invite management."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_default(self) -> WorkspaceRow:
        """The default workspace; created from the built-in wording if the migration's seed row
        is missing (a database made with `create_all` has none)."""
        row = await self._s.get(WorkspaceRow, DEFAULT_WORKSPACE_ID)
        if row is not None:
            return row
        now = utcnow()
        row = WorkspaceRow(
            id=DEFAULT_WORKSPACE_ID,
            slug=DEFAULT_SLUG,
            name=DEFAULT_NAME,
            tagline=DEFAULT_TAGLINE,
            accent_hex=DEFAULT_ACCENT,
            community_paragraph=DEFAULT_PARAGRAPH,
            active_pack="default",
            osm_signin_enabled=True,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._s.add(row)
        await self._s.flush()
        return row

    async def update(
        self, expected_version: int, values: dict[str, Any], *, now: datetime | None = None
    ) -> WorkspaceRow:
        """Apply `values` if the row is still at `expected_version`, bumping the version."""
        unknown = set(values) - set(EDITABLE)
        if unknown:
            raise ValueError(f"not editable: {sorted(unknown)}")
        row = await self.get_default()
        changed = await rowcount(
            self._s,
            sa.update(WorkspaceRow)
            .where(WorkspaceRow.id == row.id, WorkspaceRow.version == expected_version)
            .values(**values, version=WorkspaceRow.version + 1, updated_at=now or utcnow())
            .execution_options(synchronize_session=False),
        )
        if changed == 0:
            fresh = await self._s.get(WorkspaceRow, row.id, populate_existing=True)
            raise WorkspaceVersionConflict(fresh.version if fresh else 0)
        return await self._s.get(WorkspaceRow, row.id, populate_existing=True) or row

    # ------------------------------------------------------------------ claiming

    async def is_claimable(self, *, ignore_admin_invites: bool = False) -> bool:
        """True while nobody owns the workspace and no admin invite code exists for it.

        `ignore_admin_invites` is for an account the operator named in the environment: an admin
        invite does not stop that account from claiming."""
        row = await self.get_default()
        if row.owner_identity_id is not None:
            return False
        if ignore_admin_invites:
            return True
        admins = await self._s.scalar(
            sa.select(sa.func.count())
            .select_from(InviteCodeRow)
            .where(InviteCodeRow.role == "admin")
        )
        return not admins

    async def claim(
        self,
        identity_id: UUID,
        *,
        ignore_admin_invites: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """Make `identity_id` the owner if the workspace is still unclaimed. One atomic update, so
        two people clicking at once cannot both win. Returns whether this call won."""
        row = await self.get_default()
        has_admin_invite = (
            sa.select(sa.literal(1))
            .select_from(InviteCodeRow)
            .where(InviteCodeRow.role == "admin")
            .exists()
        )
        conditions = [WorkspaceRow.id == row.id, WorkspaceRow.owner_identity_id.is_(None)]
        if not ignore_admin_invites:
            conditions.append(~has_admin_invite)
        changed = await rowcount(
            self._s,
            sa.update(WorkspaceRow)
            .where(*conditions)
            .values(
                owner_identity_id=identity_id,
                version=WorkspaceRow.version + 1,
                updated_at=now or utcnow(),
            )
            .execution_options(synchronize_session=False),
        )
        await self._s.refresh(row)
        return changed == 1

    # ------------------------------------------------------------------ invites

    async def list_invites(self) -> list[InviteCodeRow]:
        """Every invite code, newest first."""
        result = await self._s.execute(
            sa.select(InviteCodeRow).order_by(InviteCodeRow.created_at.desc(), InviteCodeRow.id)
        )
        return list(result.scalars())

    async def get_invite(self, invite_id: UUID) -> InviteCodeRow | None:
        """One invite code."""
        return await self._s.get(InviteCodeRow, invite_id)

    async def revoke_invite(self, invite_id: UUID, *, now: datetime | None = None) -> int | None:
        """Disable the code, stamp the time and end the sessions it opened. Returns how many
        sessions were ended, or None when the code does not exist. Revoking twice is harmless."""
        row = await self._s.get(InviteCodeRow, invite_id)
        if row is None:
            return None
        if row.revoked_at is None:
            row.revoked_at = now or utcnow()
        row.disabled = True
        await self._s.flush()
        result = await self._s.execute(
            sa.update(SessionRow)
            .where(SessionRow.invite_code_id == invite_id, SessionRow.revoked.is_(False))
            .values(revoked=True)
            .execution_options(synchronize_session=False)
        )
        await self._s.flush()
        return int(result.rowcount)  # type: ignore[attr-defined]

"""OpenStreetMap identities and the pending sign-in states. Never commits; never stores a token."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.persistence.repos._common import rowcount, utcnow
from cso.persistence.tables import IdentityRow, OAuthStateRow


class IdentitiesRepo:
    """Storage for signed-in OpenStreetMap accounts and one-time sign-in states."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(
        self,
        *,
        osm_uid: int,
        display_name: str,
        account_created: str | None,
        now: datetime | None = None,
    ) -> IdentityRow:
        """The identity for this OSM account; a returning account has its name and login time
        refreshed (an OSM user may rename themselves)."""
        moment = now or utcnow()
        result = await self._s.execute(sa.select(IdentityRow).where(IdentityRow.osm_uid == osm_uid))
        row = result.scalars().first()
        if row is None:
            row = IdentityRow(
                id=uuid4(),
                osm_uid=osm_uid,
                display_name=display_name,
                account_created=account_created,
                first_seen_at=moment,
                last_login_at=moment,
            )
            self._s.add(row)
        else:
            row.display_name = display_name
            row.account_created = account_created
            row.last_login_at = moment
        await self._s.flush()
        return row

    async def get(self, identity_id: UUID) -> IdentityRow | None:
        """The identity row, if it exists."""
        return await self._s.get(IdentityRow, identity_id)

    # ------------------------------------------------------------------ pending sign-ins

    async def add_state(
        self, *, state_hash: str, verifier: str, expires_at: datetime, now: datetime | None = None
    ) -> None:
        """Remember one pending sign-in, and forget the ones that have expired."""
        moment = now or utcnow()
        await self._s.execute(sa.delete(OAuthStateRow).where(OAuthStateRow.expires_at <= moment))
        self._s.add(
            OAuthStateRow(
                state_hash=state_hash, verifier=verifier, created_at=moment, expires_at=expires_at
            )
        )
        await self._s.flush()

    async def consume_state(self, state_hash: str, *, now: datetime | None = None) -> str | None:
        """The PKCE verifier for this state, once. A second use, an unknown state and an expired
        one all return None; the row is deleted either way, so a state is never reusable."""
        moment = now or utcnow()
        result = await self._s.execute(
            sa.select(OAuthStateRow).where(OAuthStateRow.state_hash == state_hash)
        )
        row = result.scalars().first()
        if row is None:
            return None
        verifier, expires_at = row.verifier, row.expires_at
        deleted = await rowcount(
            self._s, sa.delete(OAuthStateRow).where(OAuthStateRow.state_hash == state_hash)
        )
        if deleted != 1 or expires_at <= moment:  # lost a race, or too late
            return None
        return verifier

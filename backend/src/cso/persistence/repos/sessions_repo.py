"""Invite codes and sessions: storage primitives. Hashing, CSRF and roles live in `cso.api.auth`.

No plaintext secret is ever stored: invite rows hold an argon2 hash of the secret part and the
public `code_id`; session rows hold the sha256 of the cookie token and of the CSRF token.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.persistence.repos._common import utcnow
from cso.persistence.tables import InviteCodeRow, SessionRow


class SessionsRepo:
    """Repository for invite codes and sessions; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ------------------------------------------------------------------ invite codes

    async def add_invite_code(
        self,
        *,
        code_hash: str,
        role: str,
        label: str = "",
        code_id: str | None = None,
        created_by: str | None = None,
        max_uses: int | None = None,
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> InviteCodeRow:
        """Store a hashed invite code (`max_uses=None` means unlimited, `expires_at=None` never)."""
        row = InviteCodeRow(
            id=uuid4(),
            code_hash=code_hash,
            role=role,
            label=label,
            created_at=now or utcnow(),
            code_id=code_id,
            created_by=created_by,
            max_uses=max_uses,
            use_count=0,
            expires_at=expires_at,
        )
        self._s.add(row)
        await self._s.flush()
        return row

    async def get_invite_by_hash(self, code_hash: str) -> InviteCodeRow | None:
        """The enabled or disabled invite code with this hash."""
        result = await self._s.execute(
            sa.select(InviteCodeRow).where(InviteCodeRow.code_hash == code_hash)
        )
        return result.scalars().first()

    async def get_invite_by_code_id(self, code_id: str) -> InviteCodeRow | None:
        """The invite code whose public id part is `code_id`."""
        result = await self._s.execute(
            sa.select(InviteCodeRow).where(InviteCodeRow.code_id == code_id)
        )
        return result.scalars().first()

    async def consume_invite(self, invite_id: UUID, *, now: datetime | None = None) -> bool:
        """Use one login of the invite, atomically; False when it is spent, expired or disabled.

        One UPDATE with the limits in its WHERE clause, so two logins racing for the last use
        cannot both succeed.
        """
        moment = now or utcnow()
        result = await self._s.execute(
            sa.update(InviteCodeRow)
            .where(
                InviteCodeRow.id == invite_id,
                InviteCodeRow.disabled.is_(False),
                sa.or_(InviteCodeRow.expires_at.is_(None), InviteCodeRow.expires_at > moment),
                sa.or_(
                    InviteCodeRow.max_uses.is_(None),
                    InviteCodeRow.use_count < InviteCodeRow.max_uses,
                ),
            )
            .values(use_count=InviteCodeRow.use_count + 1)
            .execution_options(synchronize_session=False)
        )
        await self._s.flush()
        return result.rowcount == 1  # type: ignore[attr-defined, no-any-return]

    async def disable_invite(self, invite_id: UUID) -> bool:
        """Disable an invite code (later logins fail); False when it does not exist."""
        row = await self._s.get(InviteCodeRow, invite_id)
        if row is None:
            return False
        row.disabled = True
        await self._s.flush()
        return True

    # ------------------------------------------------------------------ sessions

    async def create_session(
        self,
        *,
        invite_code_id: UUID | None,
        display_name: str,
        role: str,
        expires_at: datetime,
        token_hash: str | None = None,
        csrf_hash: str | None = None,
        identity_id: UUID | None = None,
        now: datetime | None = None,
    ) -> SessionRow:
        """Open a session for an invite code, or for an OpenStreetMap identity (no invite)."""
        moment = now or utcnow()
        row = SessionRow(
            id=uuid4(),
            invite_code_id=invite_code_id,
            identity_id=identity_id,
            display_name=display_name,
            role=role,
            created_at=moment,
            expires_at=expires_at,
            token_hash=token_hash,
            csrf_hash=csrf_hash,
            last_seen_at=moment,
        )
        self._s.add(row)
        await self._s.flush()
        return row

    async def get(self, session_id: UUID) -> SessionRow | None:
        """The session row, whatever its state."""
        return await self._s.get(SessionRow, session_id)

    async def get_by_token_hash(self, token_hash: str) -> SessionRow | None:
        """The session row with this cookie-token hash, whatever its state."""
        result = await self._s.execute(
            sa.select(SessionRow).where(SessionRow.token_hash == token_hash)
        )
        return result.scalars().first()

    @staticmethod
    def _is_active(row: SessionRow, *, now: datetime, idle_timeout: timedelta | None) -> bool:
        if row.revoked or row.expires_at <= now:
            return False
        if idle_timeout is not None:
            seen = row.last_seen_at or row.created_at
            if seen + idle_timeout <= now:
                return False
        return True

    async def get_active(
        self,
        session_id: UUID,
        *,
        now: datetime | None = None,
        idle_timeout: timedelta | None = None,
    ) -> SessionRow | None:
        """The session if it is neither revoked, expired nor idle for too long."""
        row = await self._s.get(SessionRow, session_id)
        if row is None or not self._is_active(row, now=now or utcnow(), idle_timeout=idle_timeout):
            return None
        return row

    async def get_active_by_token_hash(
        self,
        token_hash: str,
        *,
        now: datetime | None = None,
        idle_timeout: timedelta | None = None,
    ) -> SessionRow | None:
        """Like `get_active`, found through the hash of the cookie token."""
        row = await self.get_by_token_hash(token_hash)
        if row is None or not self._is_active(row, now=now or utcnow(), idle_timeout=idle_timeout):
            return None
        return row

    async def touch(
        self,
        row: SessionRow,
        *,
        now: datetime | None = None,
        min_interval: timedelta = timedelta(seconds=60),
    ) -> bool:
        """Record activity for idle expiry, at most once per `min_interval` (saves writes)."""
        moment = now or utcnow()
        seen = row.last_seen_at or row.created_at
        if moment - seen < min_interval:
            return False
        row.last_seen_at = moment
        await self._s.flush()
        return True

    async def revoke(self, session_id: UUID) -> bool:
        """Revoke a session; returns False when it does not exist."""
        row = await self._s.get(SessionRow, session_id)
        if row is None:
            return False
        row.revoked = True
        await self._s.flush()
        return True

    async def set_role(self, session_id: UUID, role: str) -> bool:
        """Change the role of one live session (used when its owner claims the workspace)."""
        row = await self._s.get(SessionRow, session_id)
        if row is None or row.revoked:
            return False
        row.role = role
        await self._s.flush()
        return True

    async def revoke_for_invite(self, invite_id: UUID) -> int:
        """Revoke every live session opened with this invite code; returns how many."""
        result = await self._s.execute(
            sa.update(SessionRow)
            .where(SessionRow.invite_code_id == invite_id, SessionRow.revoked.is_(False))
            .values(revoked=True)
            .execution_options(synchronize_session=False)
        )
        await self._s.flush()
        return int(result.rowcount)  # type: ignore[attr-defined]

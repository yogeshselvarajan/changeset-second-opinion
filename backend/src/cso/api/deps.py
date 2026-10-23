"""Roles and the authorization dependencies, backed by server-side sessions.

Routers declare what they need with `Depends(require_role(Role.REVIEWER))`; they never read the
cookie themselves. `get_principal` resolves the `cso_session` cookie to a session and, for
non-GET requests, checks the CSRF token bound to that session.

Modes:
- replay: an anonymous caller is the read-only viewer; a reviewer or admin needs a session.
- live: a session is required for everything except the endpoints that use
  `get_optional_principal` (login, logout, `/me`). Set `AuthConfig.allow_anonymous_read_in_live`
  to let anonymous callers read in live mode too.

Tests and tools can still replace the dependency with
`app.dependency_overrides[get_principal] = lambda: some_principal`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from fastapi import Depends, Request

from cso.api.auth_core import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SAFE_METHODS,
    SESSION_COOKIE,
    get_config,
    resolve_session,
    session_factory_for,
    verify_csrf_binding,
)
from cso.api.problems import ForbiddenError, UnauthorizedError
from cso.persistence.db import session_scope


class Role(StrEnum):
    """Authorization level of the caller, ordered viewer < reviewer < admin."""

    VIEWER = "viewer"
    REVIEWER = "reviewer"
    ADMIN = "admin"


ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.REVIEWER: 1, Role.ADMIN: 2}


@dataclass(frozen=True)
class Principal:
    """The authenticated caller; `anonymous` callers have no session.

    For a session, `id` is the session id as text (outcomes are attributed to it) and
    `session_id` is the same value as a UUID.
    """

    id: str
    display_name: str | None
    role: Role
    anonymous: bool = False
    session_id: UUID | None = None
    identity_id: UUID | None = None  # set when the session came from signing in with OpenStreetMap


ANONYMOUS_VIEWER = Principal(id="anonymous", display_name=None, role=Role.VIEWER, anonymous=True)

_PRINCIPAL_STATE = "cso_principal"


async def get_optional_principal(request: Request = None) -> Principal:  # type: ignore[assignment]
    """The session's principal, or the anonymous viewer; never raises for a missing session.

    Used by `/auth/login`, `/auth/logout` and `/me`. Called without a request (as the unit
    tests of the placeholder did) it returns the anonymous viewer. For non-GET requests with a
    live session it also enforces the CSRF binding, so a forged cross-site POST fails with 403.
    """
    if request is None:
        return ANONYMOUS_VIEWER
    cached = getattr(request.state, _PRINCIPAL_STATE, None)
    if isinstance(cached, Principal):
        return cached
    principal = await _principal_from_cookie(request)
    setattr(request.state, _PRINCIPAL_STATE, principal)
    return principal


async def _principal_from_cookie(request: Request) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return ANONYMOUS_VIEWER  # no cookie: no database work for anonymous reads
    config = get_config(request)
    async with session_scope(session_factory_for(request)) as db:
        row = await resolve_session(db, config, token)
    if row is None:
        return ANONYMOUS_VIEWER
    if request.method.upper() not in SAFE_METHODS:
        verify_csrf_binding(row, request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE))
    return Principal(
        id=str(row.id),
        display_name=row.display_name,
        role=Role(row.role),
        anonymous=False,
        session_id=row.id,
        identity_id=row.identity_id,
    )


async def get_principal(request: Request = None) -> Principal:  # type: ignore[assignment]
    """The current caller; in live mode an anonymous caller is refused with 401.

    Without a request (a direct call in a unit test) it is the anonymous viewer.
    """
    principal = await get_optional_principal(request)
    if request is not None and principal.anonymous:
        config = get_config(request)
        if config.mode == "live" and not config.allow_anonymous_read_in_live:
            raise UnauthorizedError("Sign in with an invite code to use this service.")
    return principal


def has_role(principal: Principal, required: Role) -> bool:
    """True when the principal's role is at least `required`."""
    return ROLE_RANK[principal.role] >= ROLE_RANK[required]


def check_role(principal: Principal, required: Role) -> Principal:
    """Raise 401 for an anonymous caller that needs more than viewer, 403 for a lower role."""
    if has_role(principal, required):
        return principal
    if principal.anonymous:
        raise UnauthorizedError("Sign in with an invite code to use this endpoint.")
    raise ForbiddenError(f"The {required.value} role is needed for this endpoint.")


def require_role(required: Role) -> Callable[..., Awaitable[Principal]]:
    """FastAPI dependency factory: `Depends(require_role(Role.REVIEWER))`."""

    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:  # noqa: B008
        return check_role(principal, required)

    return dependency

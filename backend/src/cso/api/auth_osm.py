"""Sign in with OpenStreetMap: `GET /auth/osm/start` and `GET /auth/osm/callback`.

OAuth 2.0 authorization code with PKCE, scope `read_prefs` only (so the token can change nothing
on the map). The flow keeps three checks apart:

- `state` is random, stored hashed on the server for ten minutes and usable once;
- the PKCE verifier lives on the server next to it and never reaches the browser;
- a short-lived HttpOnly cookie carries the same `state`, so a callback URL that an attacker
  started in their own browser is refused when it arrives in someone else's (login CSRF).

Every failure sends the browser back to `/login?osm_error=<code>`; no code carries a secret. The
access token lives inside one call of `OsmTokenClient` and is never stored. A signed-in account
gets the reviewer role. Admin comes from an invite code, or from the accounts the operator named in
`CSO_BOOTSTRAP_ADMIN_OSM_UIDS`: the first of them to sign in claims a fresh workspace. Nobody else
can claim it, so finding the URL of a new deployment gives no one admin.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cso.adapters.osm.oauth import (
    OsmSignInError,
    OsmTokenClient,
    authorize_url,
    new_code_verifier,
    new_state,
)
from cso.api.auth_core import (
    SESSION_COOKIE,
    AuthConfig,
    clean_display_name,
    client_ip,
    get_auth_db,
    get_config,
    request_is_secure,
    set_login_cookies,
    sha256_hex,
)
from cso.api.db import SettingsDep
from cso.api.problems import NotFoundError, problem_responses
from cso.api.security import get_limiter
from cso.persistence.repos._common import utcnow
from cso.persistence.repos.audit_repo import AuditRepo
from cso.persistence.repos.identities_repo import IdentitiesRepo
from cso.persistence.repos.sessions_repo import SessionsRepo
from cso.persistence.repos.workspace_repo import WorkspaceRepo
from cso.settings import Settings

log = structlog.get_logger("cso.auth.osm")

router = APIRouter(tags=["auth"])

STATE_COOKIE = "cso_osm_state"
STATE_COOKIE_PATH = "/api/v1/auth/osm"
STATE_TTL = timedelta(minutes=10)
SIGNIN_ROLE = "reviewer"
ADMIN_ROLE = "admin"  # only for the account that claimed the workspace

ERROR_DENIED = "denied"
ERROR_EXPIRED = "expired"
ERROR_FAILED = "failed"
ERROR_BUSY = "busy"
ERROR_NOT_ALLOWED = "not_allowed"


def get_token_client(settings: SettingsDep) -> Iterator[OsmTokenClient]:
    """The token client for the configured OSM application (a dependency, so tests swap it)."""
    secret = settings.osm_oauth_client_secret
    if not settings.osm_oauth_enabled or secret is None or settings.osm_oauth_redirect_url is None:
        raise NotFoundError("Sign in with OpenStreetMap is not set up.")
    client = OsmTokenClient(
        client_id=settings.osm_oauth_client_id or "",
        client_secret=secret.get_secret_value(),
        redirect_url=settings.osm_oauth_redirect_url,
        user_agent=settings.user_agent,
    )
    yield client


async def is_bootstrap_admin(settings: Settings, db: AsyncSession, identity_id: UUID) -> bool:
    """True when this signed-in account is one the operator named as allowed to become admin."""
    uids = settings.bootstrap_admin_uids
    if not uids:
        return False
    identity = await IdentitiesRepo(db).get(identity_id)
    return identity is not None and identity.osm_uid in uids


async def osm_signin_open(settings: Settings, db: AsyncSession) -> bool:
    """True when the server holds the OSM application and the workspace has not switched it off."""
    if not settings.osm_oauth_enabled:
        return False
    return (await WorkspaceRepo(db).get_default()).osm_signin_enabled


def _web_url(settings: Settings, path: str) -> str:
    return f"{settings.web_base_url}{path}"


def _failure(settings: Settings, request: Request, config: AuthConfig, code: str) -> Response:
    """Back to the login screen with a reason; the state cookie is cleared either way."""
    response = RedirectResponse(_web_url(settings, f"/login?osm_error={code}"), status_code=302)
    response.delete_cookie(
        STATE_COOKIE,
        path=STATE_COOKIE_PATH,
        secure=request_is_secure(request, config),
        httponly=True,
        samesite="lax",
    )
    return response


def _rate_limited(request: Request, config: AuthConfig) -> bool:
    wait = get_limiter(request.app).hit(
        f"osm_signin:ip:{client_ip(request, config)}",
        capacity=config.login_attempts,
        window_s=config.login_window.total_seconds(),
    )
    return wait is not None


@router.get(
    "/auth/osm/start",
    status_code=302,
    response_class=Response,
    summary="Begin signing in with OpenStreetMap",
    responses=problem_responses(404),
)
async def osm_start(
    request: Request,
    settings: SettingsDep,
    db: Annotated[AsyncSession, Depends(get_auth_db)],
) -> Response:
    """Send the browser to OpenStreetMap to approve a read-only sign-in."""
    config = get_config(request)
    if not settings.osm_oauth_redirect_url or not await osm_signin_open(settings, db):
        raise NotFoundError("Sign in with OpenStreetMap is not set up.")
    if _rate_limited(request, config):
        return _failure(settings, request, config, ERROR_BUSY)
    state, verifier = new_state(), new_code_verifier()
    await IdentitiesRepo(db).add_state(
        state_hash=sha256_hex(state), verifier=verifier, expires_at=utcnow() + STATE_TTL
    )
    await db.commit()  # the callback may arrive before this request's transaction would close
    response = RedirectResponse(
        authorize_url(
            client_id=settings.osm_oauth_client_id or "",
            redirect_url=settings.osm_oauth_redirect_url,
            state=state,
            verifier=verifier,
        ),
        status_code=302,
    )
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=int(STATE_TTL.total_seconds()),
        path=STATE_COOKIE_PATH,
        secure=request_is_secure(request, config),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get(
    "/auth/osm/callback",
    status_code=302,
    response_class=Response,
    summary="Finish signing in with OpenStreetMap",
    responses=problem_responses(404),
)
async def osm_callback(
    request: Request,
    settings: SettingsDep,
    db: Annotated[AsyncSession, Depends(get_auth_db)],
    tokens: Annotated[OsmTokenClient, Depends(get_token_client)],
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> Response:
    """Check `state`, trade the code for a profile, and open a reviewer session."""
    config = get_config(request)
    if _rate_limited(request, config):
        return _failure(settings, request, config, ERROR_BUSY)
    if not await osm_signin_open(settings, db):  # switched off after the flow began
        return _failure(settings, request, config, ERROR_EXPIRED)
    repo = IdentitiesRepo(db)
    cookie_state = request.cookies.get(STATE_COOKIE)
    # The state must come back in the URL and in this browser's cookie, and must match.
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        if state:
            await repo.consume_state(sha256_hex(state))  # a state that failed the check is spent
            await db.commit()
        log.info("auth.osm_refused", reason="state_mismatch")
        return _failure(settings, request, config, ERROR_EXPIRED)
    verifier = await repo.consume_state(sha256_hex(state))
    await db.commit()  # the state is spent from here on, whatever happens next
    if verifier is None:
        log.info("auth.osm_refused", reason="state_unknown_or_replayed")
        return _failure(settings, request, config, ERROR_EXPIRED)
    if error is not None or not code:
        log.info("auth.osm_refused", reason="denied")
        return _failure(settings, request, config, ERROR_DENIED)

    try:
        profile = await tokens.profile_for_code(code, verifier)
    except OsmSignInError as exc:
        log.info("auth.osm_refused", reason=exc.reason)
        return _failure(settings, request, config, ERROR_FAILED)
    allowed = settings.osm_signin_uids
    if allowed and profile.uid not in allowed:
        log.info("auth.osm_refused", reason="uid_not_allowed")
        return _failure(settings, request, config, ERROR_NOT_ALLOWED)

    now = utcnow()
    name = clean_display_name(profile.display_name)
    identity = await IdentitiesRepo(db).upsert(
        osm_uid=profile.uid,
        display_name=name,
        account_created=profile.account_created,
        now=now,
    )
    workspaces = WorkspaceRepo(db)
    if profile.uid in settings.bootstrap_admin_uids and await workspaces.claim(
        identity.id, ignore_admin_invites=True, now=now
    ):
        await AuditRepo(db).append(
            actor=name,
            action="workspace.claimed",
            payload={"identity_id": str(identity.id), "via": "bootstrap_env"},
            now=now,
        )
    # The account that claimed the workspace is its admin on every later sign-in.
    owner = (await workspaces.get_default()).owner_identity_id
    role = ADMIN_ROLE if owner is not None and owner == identity.id else SIGNIN_ROLE
    sessions = SessionsRepo(db)
    previous = request.cookies.get(SESSION_COOKIE)
    if previous:  # a new sign-in replaces the old session (no fixation)
        old = await sessions.get_by_token_hash(sha256_hex(previous))
        if old is not None and not old.revoked:
            await sessions.revoke(old.id)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session = await sessions.create_session(
        invite_code_id=None,
        identity_id=identity.id,
        display_name=name,
        role=role,
        expires_at=now + config.session_ttl,
        token_hash=sha256_hex(token),
        csrf_hash=sha256_hex(csrf),
        now=now,
    )
    await AuditRepo(db).append(
        actor=name,
        action="auth.osm_login",
        payload={"role": role, "osm_uid": profile.uid},
        session_id=session.id,
        now=now,
    )
    await db.commit()
    log.info("auth.osm_login", role=role)
    response = RedirectResponse(_web_url(settings, "/queue"), status_code=302)
    set_login_cookies(response, request, config, token, csrf)
    response.delete_cookie(
        STATE_COOKIE,
        path=STATE_COOKIE_PATH,
        secure=request_is_secure(request, config),
        httponly=True,
        samesite="lax",
    )
    return response

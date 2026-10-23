"""Auth endpoints: `POST /auth/login`, `POST /auth/logout`, `GET /me`.

Mount with `app.include_router(auth_router, prefix="/api/v1")`. The routes carry no prefix.
Login failures are uniform (401, same message) whatever the reason; see `auth_core.login`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cso.api.auth_core import (
    SESSION_COOKIE,
    InviteHasher,
    clear_login_cookies,
    client_ip,
    get_auth_db,
    get_config,
    get_hasher,
    login,
    logout,
    set_login_cookies,
)
from cso.api.auth_osm import is_bootstrap_admin, osm_signin_open
from cso.api.db import SettingsDep
from cso.api.deps import Principal, Role, get_optional_principal
from cso.api.problems import RateLimitedError, get_request_id, problem_responses
from cso.api.schemas import LoginRequest, LoginResponse, MeResponse
from cso.api.security import get_limiter, retry_after_headers
from cso.persistence.repos.sessions_repo import SessionsRepo
from cso.persistence.repos.workspace_repo import WorkspaceRepo

router = APIRouter(tags=["auth"])


def _me(
    principal: Principal, mode: str, *, osm_signin: bool = False, can_claim: bool = False
) -> MeResponse:
    return MeResponse.model_validate(
        {
            "id": principal.id,
            "display_name": principal.display_name,
            "role": principal.role,
            "mode": mode,
            "osm_signin": osm_signin,
            "via_osm": principal.identity_id is not None,
            "can_claim": can_claim,
        }
    )


@router.post(
    "/auth/login",
    response_model=LoginResponse,
    summary="Start a reviewer session with an invite code",
    responses=problem_responses(401, 429),
)
async def login_endpoint(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_auth_db),  # noqa: B008
    hasher: InviteHasher = Depends(get_hasher),  # noqa: B008
) -> LoginResponse:
    """Exchange an invite code and a display name for a session cookie."""
    config = get_config(request)
    wait = get_limiter(request.app).hit(
        f"login:ip:{client_ip(request, config)}",
        capacity=config.login_attempts,
        window_s=config.login_window.total_seconds(),
    )
    if wait is not None:
        raise RateLimitedError(
            "Too many sign-in attempts; try again later.", headers=retry_after_headers(wait)
        )
    result = await login(
        db,
        config=config,
        hasher=hasher,
        invite_code=body.invite_code,
        display_name=body.display_name,
        previous_token=request.cookies.get(SESSION_COOKIE),
        request_id=get_request_id(request),
    )
    set_login_cookies(response, request, config, result.token, result.csrf)
    principal = Principal(
        id=str(result.session.id),
        display_name=result.session.display_name,
        role=Role(result.session.role),
        session_id=result.session.id,
    )
    return LoginResponse(me=_me(principal, config.mode))


@router.post(
    "/auth/logout",
    status_code=204,
    response_class=Response,
    summary="End the current session",
    responses=problem_responses(403),
)
async def logout_endpoint(
    request: Request,
    principal: Principal = Depends(get_optional_principal),  # noqa: B008
    db: AsyncSession = Depends(get_auth_db),  # noqa: B008
) -> Response:
    """Revoke the session (if any) and expire both cookies. Idempotent."""
    config = get_config(request)
    if principal.session_id is not None:
        row = await SessionsRepo(db).get(principal.session_id)
        if row is not None:
            await logout(db, row, request_id=get_request_id(request))
    response = Response(status_code=204)
    clear_login_cookies(response, request, config)
    return response


@router.get("/me", response_model=MeResponse, summary="Current identity, role and mode")
async def me_endpoint(
    request: Request,
    settings: SettingsDep,
    principal: Principal = Depends(get_optional_principal),  # noqa: B008
    db: AsyncSession = Depends(get_auth_db),  # noqa: B008
) -> MeResponse:
    """Who the caller is; the anonymous viewer when there is no valid session."""
    # Only an OpenStreetMap session for an account the operator named in the environment, on a
    # workspace that has no owner yet, can claim it.
    can_claim = (
        principal.identity_id is not None
        and principal.role is Role.REVIEWER
        and await is_bootstrap_admin(settings, db, principal.identity_id)
        and await WorkspaceRepo(db).is_claimable(ignore_admin_invites=True)
    )
    return _me(
        principal,
        get_config(request).mode,
        osm_signin=await osm_signin_open(settings, db),
        can_claim=can_claim,
    )

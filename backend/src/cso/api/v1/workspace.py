"""Workspace settings, the public branding, the web manifest and invite management."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Header, Request, Response
from fastapi.responses import JSONResponse

from cso.api.auth_core import InviteHasher, create_invite, get_config, get_hasher
from cso.api.auth_osm import is_bootstrap_admin
from cso.api.db import SessionFactoryDep, SettingsDep
from cso.api.deps import Role
from cso.api.etag import format_etag, parse_if_match
from cso.api.problems import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
    UnprocessableError,
    get_request_id,
    problem_responses,
)
from cso.api.routing import Admin, Reviewer, actor_of, make_router
from cso.api.schemas import (
    InviteCreate,
    InviteCreated,
    InviteList,
    InviteOut,
    InviteStatus,
    MeResponse,
    PublicBranding,
    WorkspaceSettings,
    WorkspaceUpdate,
)
from cso.domain.config import CommunityConfig as DomainConfig
from cso.domain.config import ConfigError, Tone
from cso.domain.workspace import (
    NAME_MAX,
    PARAGRAPH_MAX,
    TAGLINE_MAX,
    FieldProblem,
    LogoRejected,
    accent_contrast,
    check_accent,
    check_text,
    derive_dark_accent,
    manifest_for,
    sanitize_logo,
    settings_hash,
)
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo, ConfigsRepo
from cso.persistence.repos._common import utcnow
from cso.persistence.repos.sessions_repo import SessionsRepo
from cso.persistence.repos.workspace_repo import WorkspaceRepo, WorkspaceVersionConflict
from cso.persistence.tables import InviteCodeRow, WorkspaceRow

router = make_router(tags=["workspace"])
root_router = make_router(tags=["workspace"])  # `/site.webmanifest` lives at the site root

BRANDING_CACHE = "public, max-age=300"


def _tone() -> Tone:
    """The tone rules of the shipped default pack (the banned-word floor applies to every pack)."""
    try:
        return DomainConfig.load().tone
    except ConfigError:  # pragma: no cover - the default file is part of the package
        raise UnprocessableError("The default configuration cannot be read.") from None


def _settings(row: WorkspaceRow, *, configured: bool, calibration: str | None) -> WorkspaceSettings:
    light, dark = accent_contrast(row.accent_hex)
    return WorkspaceSettings(
        name=row.name,
        tagline=row.tagline,
        accent_hex=row.accent_hex,
        accent_dark_hex=derive_dark_accent(row.accent_hex),
        logo_svg=row.logo_svg,
        community_paragraph=row.community_paragraph,
        active_pack=row.active_pack,
        calibration_version=calibration,
        osm_signin_enabled=row.osm_signin_enabled,
        osm_signin_configured=configured,
        version=row.version,
        updated_at=row.updated_at,
        accent_contrast_light=round(light, 2),
        accent_contrast_dark=round(dark, 2),
    )


def _values(row: WorkspaceRow) -> dict[str, object]:
    return {
        "name": row.name,
        "tagline": row.tagline,
        "accent_hex": row.accent_hex,
        "logo_svg": row.logo_svg,
        "community_paragraph": row.community_paragraph,
        "osm_signin_enabled": row.osm_signin_enabled,
    }


def invite_status(row: InviteCodeRow, now: datetime) -> InviteStatus:
    """active, expired, revoked or spent, for the invite table."""
    if row.revoked_at is not None or row.disabled:
        return "revoked"
    if row.expires_at is not None and row.expires_at <= now:
        return "expired"
    if row.max_uses is not None and row.use_count >= row.max_uses:
        return "spent"
    return "active"


def invite_out(row: InviteCodeRow) -> InviteOut:
    """An invite as listed (the code is never part of it)."""
    return InviteOut(
        id=row.id,
        label=row.label,
        role=Role(row.role),
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        status=invite_status(row, utcnow()),
        use_count=row.use_count,
        max_uses=row.max_uses,
        created_by=row.created_by,
    )


def _problems_to_422(problems: list[FieldProblem]) -> UnprocessableError:
    return UnprocessableError(
        "Some settings were not accepted.",
        errors=[
            {"loc": ["body", p.field], "msg": p.message, "type": "workspace_invalid"}
            for p in problems
        ],
    )


# --------------------------------------------------------------------------- settings


@router.get(
    "/settings",
    response_model=WorkspaceSettings,
    summary="The workspace settings (admin)",
    responses=problem_responses(401, 403),
)
async def get_workspace_settings(
    factory: SessionFactoryDep, settings: SettingsDep, principal: Admin
) -> Response:
    """The settings, with `ETag` carrying the version to send back as `If-Match`."""
    async with session_scope(factory) as session:
        row = await WorkspaceRepo(session).get_default()
        active = await ConfigsRepo(session).get_active()
        body = _settings(
            row,
            configured=settings.osm_oauth_enabled,
            calibration=getattr(active, "calibration_id", None),
        )
    return JSONResponse(body.model_dump(mode="json"), headers={"ETag": format_etag(body.version)})


@router.put(
    "/settings",
    response_model=WorkspaceSettings,
    summary="Save the workspace settings (admin, If-Match)",
    responses=problem_responses(401, 403, 412, 422, 428),
)
async def update_workspace_settings(
    body: WorkspaceUpdate,
    request: Request,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    principal: Admin,
    if_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Validate every field, then save with the version the admin last saw."""
    expected = parse_if_match(if_match)
    problems: list[FieldProblem] = []
    tone = _tone()
    problems += check_text("name", body.name, NAME_MAX, tone)
    problems += check_text("tagline", body.tagline, TAGLINE_MAX, tone)
    problems += check_text("community_paragraph", body.community_paragraph, PARAGRAPH_MAX, tone)
    problems += check_accent(body.accent_hex)
    logo: str | None = None
    if body.logo_svg is not None:
        try:
            logo = sanitize_logo(body.logo_svg)
        except LogoRejected as exc:
            problems.append(FieldProblem("logo_svg", str(exc)))
    if problems:
        raise _problems_to_422(problems)
    async with session_scope(factory) as session:
        repo = WorkspaceRepo(session)
        before = await repo.get_default()
        before_hash = settings_hash(_values(before))
        values = {
            "name": body.name.strip(),
            "tagline": body.tagline.strip(),
            "accent_hex": body.accent_hex.upper(),
            "community_paragraph": body.community_paragraph.strip(),
            "logo_svg": logo,
            "osm_signin_enabled": body.osm_signin_enabled,
        }
        try:
            after = await repo.update(expected, values)
        except WorkspaceVersionConflict as exc:
            raise PreconditionFailedError(
                "Someone else changed the settings. Reload them and try again.",
                current={"version": exc.current},
            ) from exc
        await AuditRepo(session).append(
            actor=actor_of(principal),
            action="settings.updated",
            session_id=principal.session_id,
            request_id=get_request_id(request),
            payload={"before": before_hash, "after": settings_hash(_values(after))},
        )
        active = await ConfigsRepo(session).get_active()
        out = _settings(
            after,
            configured=settings.osm_oauth_enabled,
            calibration=getattr(active, "calibration_id", None),
        )
    return JSONResponse(out.model_dump(mode="json"), headers={"ETag": format_etag(out.version)})


# --------------------------------------------------------------------------- claiming


@router.post(
    "/workspace/claim",
    response_model=MeResponse,
    summary="Claim an unclaimed workspace and become its admin",
    responses=problem_responses(401, 403, 409),
)
async def claim_workspace(
    request: Request,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    principal: Reviewer,
) -> MeResponse:
    """Only an OpenStreetMap account named in `CSO_BOOTSTRAP_ADMIN_OSM_UIDS` can claim, and only
    once: the update that records the owner succeeds for the first caller and is refused for
    everyone after. The session becomes admin."""
    if principal.identity_id is None or principal.session_id is None:
        raise ForbiddenError("Sign in with OpenStreetMap to claim this workspace.")
    async with session_scope(factory) as session:
        if not await is_bootstrap_admin(settings, session, principal.identity_id):
            raise ForbiddenError(
                "This account is not allowed to claim the workspace. "
                "The operator names who may in CSO_BOOTSTRAP_ADMIN_OSM_UIDS."
            )
        won = await WorkspaceRepo(session).claim(principal.identity_id, ignore_admin_invites=True)
        if not won:
            raise ConflictError("This workspace already has an admin.")
        await SessionsRepo(session).set_role(principal.session_id, Role.ADMIN.value)
        await AuditRepo(session).append(
            actor=actor_of(principal),
            action="workspace.claimed",
            session_id=principal.session_id,
            request_id=get_request_id(request),
            payload={"identity_id": str(principal.identity_id)},
        )
    admin = replace(principal, role=Role.ADMIN)
    return MeResponse.model_validate(
        {
            "id": admin.id,
            "display_name": admin.display_name,
            "role": admin.role,
            "mode": get_config(request).mode,
            "osm_signin": settings.osm_oauth_enabled,
            "via_osm": True,
            "can_claim": False,
        }
    )


# --------------------------------------------------------------------------- public branding


@router.get(
    "/public/branding",
    response_model=PublicBranding,
    summary="Name, tagline, accent and wording for the public pages (no sign-in)",
)
async def get_public_branding(factory: SessionFactoryDep, settings: SettingsDep) -> Response:
    """What a visitor may see. Cached for five minutes; carries no personal data."""
    async with session_scope(factory) as session:
        row = await WorkspaceRepo(session).get_default()
        body = PublicBranding(
            name=row.name,
            tagline=row.tagline,
            accent_hex=row.accent_hex,
            accent_dark_hex=derive_dark_accent(row.accent_hex),
            has_logo=bool(row.logo_svg),
            community_paragraph=row.community_paragraph,
            osm_signin_enabled=row.osm_signin_enabled and settings.osm_oauth_enabled,
        )
    return JSONResponse(body.model_dump(mode="json"), headers={"Cache-Control": BRANDING_CACHE})


@router.get(
    "/public/branding/logo.svg",
    summary="The workspace logo (no sign-in)",
    response_class=Response,
    responses={**problem_responses(404), 200: {"content": {"image/svg+xml": {}}}},
)
async def get_public_branding_logo(factory: SessionFactoryDep) -> Response:
    """The stored logo, which was reduced to plain shapes when it was saved."""
    async with session_scope(factory) as session:
        row = await WorkspaceRepo(session).get_default()
        logo = row.logo_svg
    if not logo:
        raise NotFoundError("This workspace has no logo.")
    return Response(
        logo,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": BRANDING_CACHE,
            "Content-Security-Policy": "default-src 'none'; style-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@root_router.get(
    "/site.webmanifest",
    summary="The web app manifest, following the workspace name",
    response_class=Response,
    responses={200: {"content": {"application/manifest+json": {}}}},
)
async def get_site_manifest(factory: SessionFactoryDep) -> Response:
    """The manifest the browser installs from; name and colour come from the workspace."""
    async with session_scope(factory) as session:
        row = await WorkspaceRepo(session).get_default()
        manifest = manifest_for(row.name, row.accent_hex)
    return JSONResponse(
        manifest,
        media_type="application/manifest+json",
        headers={"Cache-Control": BRANDING_CACHE},
    )


# --------------------------------------------------------------------------- invites


@router.get(
    "/invites",
    response_model=InviteList,
    summary="Every invite code, newest first (admin)",
    responses=problem_responses(401, 403),
)
async def list_invites(factory: SessionFactoryDep, principal: Admin) -> InviteList:
    """The invite table: label, role, dates and status. The codes themselves are not stored."""
    async with session_scope(factory) as session:
        rows = await WorkspaceRepo(session).list_invites()
        return InviteList(items=[invite_out(row) for row in rows])


@router.post(
    "/invites",
    response_model=InviteCreated,
    status_code=201,
    summary="Make an invite code (admin)",
    responses=problem_responses(401, 403, 422),
)
async def create_invite_code(
    body: InviteCreate,
    request: Request,
    factory: SessionFactoryDep,
    principal: Admin,
) -> InviteCreated:
    """The code is returned once and is not stored in a form that can be shown again."""
    hasher: InviteHasher = get_hasher(request)
    get_config(request)  # the same configuration the sign-in uses
    async with session_scope(factory) as session:
        code, row = await create_invite(
            session,
            hasher,
            role=body.role.value,
            label=body.label.strip(),
            max_uses=body.max_uses,
            ttl=timedelta(hours=body.ttl_hours) if body.ttl_hours else None,
            created_by=actor_of(principal),
        )
        await AuditRepo(session).append(
            actor=actor_of(principal),
            action="invite.created",
            session_id=principal.session_id,
            request_id=get_request_id(request),
            payload={"invite_id": str(row.id), "role": row.role, "label": row.label},
        )
        return InviteCreated(code=code, invite=invite_out(row))


@router.post(
    "/invites/{id}/revoke",
    response_model=InviteOut,
    summary="Revoke an invite code and end the sessions it opened (admin)",
    responses=problem_responses(401, 403, 404),
)
async def revoke_invite(
    id: UUID, request: Request, factory: SessionFactoryDep, principal: Admin
) -> InviteOut:
    """Later sign-ins with the code fail and its open sessions end. Revoking twice is harmless."""
    async with session_scope(factory) as session:
        repo = WorkspaceRepo(session)
        ended = await repo.revoke_invite(id)
        if ended is None:
            raise NotFoundError("The invite does not exist.")
        await AuditRepo(session).append(
            actor=actor_of(principal),
            action="invite.revoked",
            session_id=principal.session_id,
            request_id=get_request_id(request),
            payload={"invite_id": str(id), "sessions_ended": ended},
        )
        row = await repo.get_invite(id)
        if row is None:  # revoked a moment ago, so it exists; kept as a guard for the type
            raise NotFoundError("The invite does not exist.")
        return invite_out(row)

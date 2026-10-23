"""Workspace over HTTP: settings, branding, manifest and invites."""

from __future__ import annotations

import json

import httpx
import pytest
import sqlalchemy as sa
from api_support import ADMIN, REVIEWER, Caller
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_cases import assert_problem

from cso.persistence.tables import AuditEventRow, SessionRow

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"
SVG = 'xmlns="http://www.w3.org/2000/svg"'
LOGO = f'<svg {SVG} viewBox="0 0 10 10"><rect width="10" height="10" fill="#123456"/></svg>'


def body(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "Second Opinion Lyon",
        "tagline": "Local eyes on flagged edits.",
        "accent_hex": "#3A46B0",
        "community_paragraph": "We review for the Lyon mapping community.",
        "logo_svg": None,
        "osm_signin_enabled": True,
    }
    return base | over


async def current(client: httpx.AsyncClient) -> httpx.Response:
    response = await client.get(f"{API}/settings")
    assert response.status_code == 200
    return response


async def save(
    client: httpx.AsyncClient, payload: dict[str, object], version: int | None = None
) -> httpx.Response:
    if version is None:
        version = (await current(client)).json()["version"]
    return await client.put(f"{API}/settings", json=payload, headers={"If-Match": f'W/"{version}"'})


# ------------------------------------------------------------------------------------ access


async def test_only_an_admin_reads_or_changes_the_settings(
    client: httpx.AsyncClient, caller: Caller
) -> None:
    caller.principal = REVIEWER
    assert_problem(await client.get(f"{API}/settings"), 403, "forbidden")
    assert_problem(
        await client.put(f"{API}/settings", json=body(), headers={"If-Match": 'W/"1"'}),
        403,
        "forbidden",
    )
    assert_problem(await client.get(f"{API}/invites"), 403, "forbidden")
    caller.principal = ADMIN
    assert (await client.get(f"{API}/settings")).status_code == 200


async def test_the_settings_start_from_the_built_in_wording(
    client: httpx.AsyncClient, caller: Caller
) -> None:
    caller.principal = ADMIN
    response = await current(client)
    data = response.json()
    assert response.headers["etag"] == 'W/"1"'
    assert data["name"] == "Changeset Second Opinion"
    assert data["version"] == 1 and data["logo_svg"] is None
    assert data["accent_contrast_light"] >= 4.5 and data["accent_contrast_dark"] >= 4.5
    assert data["accent_dark_hex"] != data["accent_hex"]
    assert data["osm_signin_configured"] is False  # the test environment has no OSM application


# ------------------------------------------------------------------------------------ saving


async def test_a_save_needs_if_match_and_a_current_version(
    client: httpx.AsyncClient, caller: Caller
) -> None:
    caller.principal = ADMIN
    assert_problem(await client.put(f"{API}/settings", json=body()), 428, "precondition_required")
    assert_problem(
        await client.put(f"{API}/settings", json=body(), headers={"If-Match": "banana"}),
        400,
        "bad_request",
    )
    first = await save(client, body())
    assert first.status_code == 200 and first.json()["version"] == 2
    assert first.headers["etag"] == 'W/"2"'
    stale = await save(client, body(name="Someone else"), version=1)
    problem = assert_problem(stale, 412, "precondition_failed")
    assert problem["current"] == {"version": 2}
    assert (await current(client)).json()["name"] == "Second Opinion Lyon"  # the stale save lost


async def test_a_save_changes_what_a_visitor_sees_and_the_manifest(
    client: httpx.AsyncClient, caller: Caller
) -> None:
    caller.principal = ADMIN
    assert (await save(client, body(logo_svg=LOGO))).status_code == 200
    caller.principal = None  # type: ignore[assignment]
    anonymous = await client.get(f"{API}/public/branding")
    assert anonymous.status_code == 200
    data = anonymous.json()
    assert data["name"] == "Second Opinion Lyon" and data["has_logo"] is True
    assert data["accent_hex"] == "#3A46B0"
    assert anonymous.headers["cache-control"] == "public, max-age=300"
    assert "set-cookie" not in anonymous.headers
    logo = await client.get(f"{API}/public/branding/logo.svg")
    assert logo.status_code == 200 and logo.text == LOGO
    assert logo.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in logo.headers["content-security-policy"]
    manifest = (await client.get("/site.webmanifest")).json()
    assert manifest["name"] == "Second Opinion Lyon" and manifest["theme_color"] == "#3A46B0"


async def test_removing_the_logo_leaves_the_branding_without_one(
    client: httpx.AsyncClient, caller: Caller
) -> None:
    caller.principal = ADMIN
    await save(client, body(logo_svg=LOGO))
    await save(client, body(logo_svg=None))
    assert (await client.get(f"{API}/public/branding")).json()["has_logo"] is False
    assert_problem(await client.get(f"{API}/public/branding/logo.svg"), 404, "not_found")


async def test_every_failed_field_is_listed_and_nothing_is_saved(
    client: httpx.AsyncClient, caller: Caller
) -> None:
    caller.principal = ADMIN
    response = await save(
        client,
        body(
            name="x" * 49,
            tagline="We stop vandalism",
            accent_hex="#F0F0F0",
            community_paragraph="  ",
            logo_svg=f"<svg {SVG}><script>alert(1)</script></svg>",
        ),
    )
    assert response.status_code == 422
    errors = response.json()["errors"]
    fields = {e["loc"][-1] for e in errors}
    assert fields == {"name", "tagline", "accent_hex", "community_paragraph", "logo_svg"}
    assert "vandalism" not in response.text.lower().replace("we stop vandalism", "")
    assert (await current(client)).json()["version"] == 1


@pytest.mark.parametrize(
    "svg",
    [
        f"<svg {SVG} onload='x()'><rect/></svg>",
        f"<svg {SVG}><foreignObject/></svg>",
        f"<svg {SVG}><a href='https://x.test'><rect/></a></svg>",
        '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">]>' + f"<svg {SVG}>&a;</svg>",
    ],
)
async def test_a_hostile_logo_is_a_422_that_names_the_logo(
    client: httpx.AsyncClient, caller: Caller, svg: str
) -> None:
    caller.principal = ADMIN
    response = await save(client, body(logo_svg=svg))
    assert response.status_code == 422
    assert [e["loc"][-1] for e in response.json()["errors"]] == ["logo_svg"]


async def test_a_save_writes_an_audit_event_with_hashes_and_no_logo_text(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    caller.principal = ADMIN
    await save(client, body(logo_svg=LOGO))
    async with factory() as session:
        rows = (
            (await session.execute(sa.select(AuditEventRow).order_by(AuditEventRow.id)))
            .scalars()
            .all()
        )
    updated = [r for r in rows if r.action == "settings.updated"]
    assert len(updated) == 1
    event = updated[0]
    assert event.actor == "admin:Ada Admin"
    assert (
        set(event.payload) == {"before", "after"}
        and event.payload["before"] != event.payload["after"]
    )
    assert "svg" not in json.dumps(event.payload).lower()


# ------------------------------------------------------------------------------------ invites


async def test_an_invite_is_made_listed_used_and_revoked(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    caller.principal = ADMIN
    created = await client.post(
        f"{API}/invites", json={"role": "reviewer", "label": "Lyon team", "max_uses": 5}
    )
    assert created.status_code == 201
    code = created.json()["code"]
    invite = created.json()["invite"]
    assert code.startswith("cso-") and invite["status"] == "active"
    assert invite["created_by"] == "admin:Ada Admin" and invite["label"] == "Lyon team"

    listed = (await client.get(f"{API}/invites")).json()["items"]
    assert [i["id"] for i in listed] == [invite["id"]]
    assert code not in json.dumps(listed)  # the code is shown once and never listed

    # the code signs someone in (a real login, not the overridden principal)
    login = await client.post(
        f"{API}/auth/login", json={"invite_code": code, "display_name": "Lyon mapper"}
    )
    assert login.status_code == 200

    revoked = await client.post(f"{API}/invites/{invite['id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked" and revoked.json()["revoked_at"]
    async with factory() as session:
        sessions = (await session.execute(sa.select(SessionRow))).scalars().all()
        actions = [r.action for r in (await session.execute(sa.select(AuditEventRow))).scalars()]
    assert [s.revoked for s in sessions] == [True]  # the session it opened ended
    assert "invite.created" in actions and "invite.revoked" in actions

    again = await client.post(
        f"{API}/auth/login", json={"invite_code": code, "display_name": "Lyon mapper"}
    )
    assert again.status_code == 401 and "revoked" in again.json()["detail"]
    assert (await client.post(f"{API}/invites/{invite['id']}/revoke")).status_code == 200


async def test_an_invite_with_a_lifetime_shows_when_it_ends(
    client: httpx.AsyncClient, caller: Caller
) -> None:
    caller.principal = ADMIN
    created = await client.post(f"{API}/invites", json={"label": "short", "ttl_hours": 2})
    expires = created.json()["invite"]["expires_at"]
    assert expires is not None and created.json()["invite"]["role"] == "reviewer"


async def test_invite_input_is_checked(client: httpx.AsyncClient, caller: Caller) -> None:
    caller.principal = ADMIN
    for payload in (
        {"role": "emperor"},
        {"label": "x" * 81},
        {"ttl_hours": 0},
        {"max_uses": 0},
        {"unknown": 1},
    ):
        assert (await client.post(f"{API}/invites", json=payload)).status_code == 422, payload
    assert_problem(await client.post(f"{API}/invites/not-a-uuid/revoke"), 404, "not_found")
    assert_problem(
        await client.post(f"{API}/invites/00000000-0000-4000-8000-0000000000aa/revoke"),
        404,
        "not_found",
    )

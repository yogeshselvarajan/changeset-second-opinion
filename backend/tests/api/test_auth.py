"""Auth acceptance: sessions, cookies, roles, CSRF, origin checks, logout, modes."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from auth_support import build_env, client_for, csrf, login_as, mint_invite, sql

from cso.api.deps import ANONYMOUS_VIEWER, get_principal


def _cookie_headers(response_headers: list[str]) -> dict[str, str]:
    """Set-Cookie header lines keyed by cookie name."""
    return {line.split("=", 1)[0]: line for line in response_headers}


# ------------------------------------------------------------------------------ login and /me


async def test_login_creates_a_reviewer_session(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        code = await mint_invite(env)
        response = await login_as(client, code, "mapper_a")
        assert response.status_code == 200
        assert response.json()["me"] == {
            "id": response.json()["me"]["id"],
            "display_name": "mapper_a",
            "role": "reviewer",
            "mode": "replay",
            "osm_signin": False,
            "via_osm": False,
            "can_claim": False,
        }
        me = await client.get("/api/v1/me")
        assert me.json()["role"] == "reviewer" and me.json()["display_name"] == "mapper_a"


async def test_me_is_the_anonymous_viewer_without_a_session(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        body = (await client.get("/api/v1/me")).json()
        assert body["role"] == "viewer" and body["id"] == "anonymous" and body["mode"] == "replay"
        assert body.get("display_name") is None


async def test_placeholder_style_call_without_a_request_is_still_the_anonymous_viewer() -> None:
    assert await get_principal() is ANONYMOUS_VIEWER


async def test_display_name_is_cleaned_and_must_have_visible_characters(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        code = await mint_invite(env, max_uses=3)
        ok = await login_as(client, code, "  Mapper​ \x07 A  ")
        assert ok.json()["me"]["display_name"] == "Mapper A"
        async with client_for(env) as other:
            empty = await login_as(other, code, "​\x07")
            assert empty.status_code == 400
            assert empty.headers["content-type"].startswith("application/problem+json")


# ------------------------------------------------------------------------------ cookie flags


async def test_cookie_flags_over_https(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env, "https://testserver") as client:
        response = await login_as(client, await mint_invite(env))
        cookies = _cookie_headers(response.headers.get_list("set-cookie"))
        session = cookies["cso_session"].lower()
        assert "httponly" in session and "secure" in session
        assert "samesite=lax" in session and "path=/api" in session and "max-age=43200" in session
        readable = cookies["cso_csrf"].lower()
        assert "httponly" not in readable and "secure" in readable
        assert "samesite=lax" in readable and "path=/;" in readable + ";"


async def test_secure_flag_is_dropped_only_for_plain_http_loopback(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        code = await mint_invite(env, max_uses=3)
        async with client_for(env, "http://localhost") as local:
            line = (await login_as(local, code)).headers.get_list("set-cookie")[0].lower()
            assert "secure" not in line and "httponly" in line
        async with client_for(env, "http://public.example") as public:
            line = (await login_as(public, code)).headers.get_list("set-cookie")[0].lower()
            assert "secure" in line  # fails closed rather than sending a session in clear


async def test_cookie_secure_can_be_forced_off_and_on(tmp_path: Path) -> None:
    async with build_env(tmp_path, cookie_secure=False) as env:
        async with client_for(env, "https://testserver") as client:
            line = (await login_as(client, await mint_invite(env))).headers.get_list("set-cookie")
            assert all("secure" not in cookie.lower() for cookie in line)


# ------------------------------------------------------------------------------ roles


async def test_role_matrix(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        viewer_code = await mint_invite(env, "viewer")
        reviewer_code = await mint_invite(env, "reviewer")
        admin_code = await mint_invite(env, "admin")

        async with client_for(env) as anon:
            assert (await anon.get("/api/v1/ping")).status_code == 200
            denied = await anon.post("/api/v1/write")
            assert denied.status_code == 401
            assert denied.headers["content-type"].startswith("application/problem+json")

        async with client_for(env) as viewer:
            await login_as(viewer, viewer_code)
            assert (await viewer.get("/api/v1/ping")).status_code == 200
            blocked = await viewer.post("/api/v1/write", headers=csrf(viewer))
            assert blocked.status_code == 403
            assert blocked.json()["type"] == "urn:cso:problem:forbidden"

        async with client_for(env) as reviewer:
            await login_as(reviewer, reviewer_code)
            assert (await reviewer.post("/api/v1/write", headers=csrf(reviewer))).status_code == 200
            assert (await reviewer.get("/api/v1/admin")).status_code == 403
            assert (await reviewer.post("/api/v1/admin", headers=csrf(reviewer))).status_code == 403

        async with client_for(env) as admin:
            await login_as(admin, admin_code)
            assert (await admin.get("/api/v1/admin")).status_code == 200
            assert (await admin.post("/api/v1/admin", headers=csrf(admin))).status_code == 200
            assert (await admin.post("/api/v1/write", headers=csrf(admin))).status_code == 200


async def test_the_session_id_is_the_attribution_id(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        login = await login_as(client, await mint_invite(env), "mapper_a")
        wrote = await client.post("/api/v1/write", headers=csrf(client))
        assert wrote.json() == {"by": "mapper_a", "id": login.json()["me"]["id"]}


# ------------------------------------------------------------------------------ CSRF


async def test_csrf_header_is_required_wrong_values_fail_and_the_right_one_passes(
    tmp_path: Path,
) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env))
        missing = await client.post("/api/v1/write")
        assert missing.status_code == 403
        assert missing.json()["type"] == "urn:cso:problem:csrf_invalid"
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert (await client.post("/api/v1/write", headers={"X-CSRF": "nope"})).status_code == 403
        assert (await client.post("/api/v1/write", headers=csrf(client))).status_code == 200


async def test_a_forged_csrf_cookie_that_the_server_never_issued_is_rejected(
    tmp_path: Path,
) -> None:
    """Double-submit alone is not enough: the token is also bound to the session row."""
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env))
        client.cookies.set("cso_csrf", "attacker-chosen-value", path="/")
        forged = await client.post("/api/v1/write", headers={"X-CSRF": "attacker-chosen-value"})
        assert forged.status_code == 403
        assert forged.json()["type"] == "urn:cso:problem:csrf_invalid"


async def test_csrf_is_enforced_for_routes_that_have_no_principal_dependency(
    tmp_path: Path,
) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env))
        assert (await client.post("/api/v1/open")).status_code == 403
        assert (await client.post("/api/v1/open", headers=csrf(client))).status_code == 200


async def test_get_requests_need_no_csrf_header(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env))
        assert (await client.get("/api/v1/ping")).status_code == 200


# ------------------------------------------------------------------------------ origin


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://testserver.evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
async def test_cross_origin_mutations_are_rejected(tmp_path: Path, headers: dict[str, str]) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env))
        response = await client.post("/api/v1/write", headers={**csrf(client), **headers})
        assert response.status_code == 403
        assert response.json()["type"] == "urn:cso:problem:cross_origin_rejected"
        assert response.headers["content-type"].startswith("application/problem+json")


async def test_same_origin_requests_pass_and_cross_origin_login_is_rejected(
    tmp_path: Path,
) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        code = await mint_invite(env, max_uses=5)
        same = await client.post(
            "/api/v1/auth/login",
            json={"invite_code": code, "display_name": "a"},
            headers={"Origin": "http://testserver"},
        )
        assert same.status_code == 200
        async with client_for(env) as other:
            evil = await other.post(
                "/api/v1/auth/login",
                json={"invite_code": code, "display_name": "a"},
                headers={"Origin": "https://evil.example"},
            )
            assert evil.status_code == 403


# ------------------------------------------------------------------------------ logout


async def test_logout_revokes_the_session_clears_cookies_and_is_audited(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env), "mapper_a")
        token = client.cookies.get("cso_session")
        headers = csrf(client)
        out = await client.post("/api/v1/auth/logout", headers=headers)
        assert out.status_code == 204
        cleared = " ".join(out.headers.get_list("set-cookie")).lower()
        assert "cso_session=" in cleared and "max-age=0" in cleared

        # The old token no longer works, even replayed by hand.
        async with client_for(env) as replay:
            replay.cookies.set("cso_session", token or "", path="/api")
            replay.cookies.set("cso_csrf", headers["X-CSRF"], path="/")
            assert (await replay.post("/api/v1/write", headers=headers)).status_code == 401
            assert (await replay.get("/api/v1/me")).json()["role"] == "viewer"

        actions = [row[0] for row in await sql(env, "SELECT action FROM audit_events ORDER BY id")]
        assert actions == ["auth.login", "auth.logout"]


async def test_logout_needs_the_csrf_header_when_a_session_exists(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env))
        assert (await client.post("/api/v1/auth/logout")).status_code == 403
        assert (await client.get("/api/v1/ping")).status_code == 200  # still signed in


async def test_logout_without_a_session_is_a_harmless_204(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        assert (await client.post("/api/v1/auth/logout")).status_code == 204


# ------------------------------------------------------------------------------ expiry, rotation


async def test_a_session_past_its_absolute_expiry_is_refused(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        await login_as(client, await mint_invite(env))
        await sql(env, "UPDATE sessions SET expires_at = :t", t="2000-01-01 00:00:00.000000")
        assert (await client.post("/api/v1/write", headers=csrf(client))).status_code == 401
        assert (await client.get("/api/v1/me")).json()["role"] == "viewer"


async def test_an_idle_session_expires(tmp_path: Path) -> None:
    async with build_env(tmp_path, idle_timeout=timedelta(minutes=30)) as env:
        async with client_for(env) as client:
            await login_as(client, await mint_invite(env))
            await sql(env, "UPDATE sessions SET last_seen_at = :t", t="2000-01-01 00:00:00.000000")
            assert (await client.post("/api/v1/write", headers=csrf(client))).status_code == 401


async def test_activity_keeps_a_session_alive_within_the_idle_window(tmp_path: Path) -> None:
    async with build_env(tmp_path, idle_timeout=timedelta(minutes=30)) as env:
        async with client_for(env) as client:
            await login_as(client, await mint_invite(env))
            for _ in range(3):
                assert (await client.post("/api/v1/write", headers=csrf(client))).status_code == 200


async def test_login_rotates_the_session_and_revokes_the_previous_one(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        code = await mint_invite(env, max_uses=2)
        await login_as(client, code, "mapper_a")
        first_token, first_csrf = client.cookies.get("cso_session"), client.cookies.get("cso_csrf")
        await login_as(client, code, "mapper_a")
        assert client.cookies.get("cso_session") != first_token
        assert client.cookies.get("cso_csrf") != first_csrf
        assert (await client.post("/api/v1/write", headers=csrf(client))).status_code == 200

        async with client_for(env) as old:
            old.cookies.set("cso_session", first_token or "", path="/api")
            old.cookies.set("cso_csrf", first_csrf or "", path="/")
            stale = await old.post("/api/v1/write", headers={"X-CSRF": first_csrf or ""})
            assert stale.status_code == 401
        revoked = await sql(env, "SELECT revoked FROM sessions ORDER BY created_at")
        assert [bool(row[0]) for row in revoked] == [True, False]


# ------------------------------------------------------------------------------ modes


async def test_live_mode_requires_a_session_except_for_login_and_me(tmp_path: Path) -> None:
    async with build_env(tmp_path, mode="live") as env, client_for(env) as client:
        refused = await client.get("/api/v1/ping")
        assert refused.status_code == 401
        assert refused.headers["content-type"].startswith("application/problem+json")
        me = (await client.get("/api/v1/me")).json()
        assert me["role"] == "viewer" and me["mode"] == "live"
        await login_as(client, await mint_invite(env))
        assert (await client.get("/api/v1/ping")).status_code == 200


async def test_live_mode_can_allow_anonymous_reading(tmp_path: Path) -> None:
    async with build_env(tmp_path, mode="live", allow_anonymous_read_in_live=True) as env:
        async with client_for(env) as client:
            assert (await client.get("/api/v1/ping")).status_code == 200
            assert (await client.post("/api/v1/write")).status_code == 401


async def test_replay_mode_lets_anonymous_callers_read_but_not_write(tmp_path: Path) -> None:
    async with build_env(tmp_path, mode="replay") as env, client_for(env) as client:
        assert (await client.get("/api/v1/ping")).status_code == 200
        assert (await client.post("/api/v1/write")).status_code == 401


# ------------------------------------------------------------------------------ uniform failures


async def test_every_kind_of_bad_code_fails_the_same_way(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        good = await mint_invite(env, max_uses=1)
        wrong_secret = good[:-1] + ("A" if good[-1] != "A" else "B")
        unknown_id = "cso-00000000-" + good.split("-", 2)[2]
        async with client_for(env) as client:
            assert (await login_as(client, good)).status_code == 200  # spends the only use
        bodies = []
        for attempt in (wrong_secret, unknown_id, "not-a-code"):
            async with client_for(env) as client:
                response = await login_as(client, attempt)
                assert response.status_code == 401, attempt
                assert "set-cookie" not in response.headers
                body = response.json()
                body.pop("request_id", None)
                bodies.append(json.dumps(body, sort_keys=True))
        assert len(set(bodies)) == 1  # a code that is not real says nothing about why


async def test_a_real_code_that_is_refused_says_which_way(tmp_path: Path) -> None:
    """Only the holder of the secret reaches this answer, so it tells them what to ask for."""
    async with build_env(tmp_path) as env:
        spent = await mint_invite(env, max_uses=1, label="spent")
        async with client_for(env) as client:
            assert (await login_as(client, spent)).status_code == 200
        revoked = await mint_invite(env, label="revoked")
        await sql(env, "UPDATE invite_codes SET disabled = 1 WHERE label = 'revoked'")
        expired = await mint_invite(env, ttl=timedelta(seconds=-1), label="expired")
        for code, word in ((spent, "used"), (revoked, "revoked"), (expired, "expired")):
            async with client_for(env) as client:
                response = await login_as(client, code)
                assert response.status_code == 401
                assert "set-cookie" not in response.headers
                assert word in response.json()["detail"]


# ------------------------------------------------------------------------------ audit hygiene


async def test_audit_rows_exist_and_carry_no_secrets(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        code = await mint_invite(env)
        async with client_for(env) as bad:
            await login_as(bad, code[:-1] + "!", "intruder")
        await login_as(client, code, "mapper_a")
        token, token_csrf = client.cookies.get("cso_session"), client.cookies.get("cso_csrf")
        await client.post("/api/v1/auth/logout", headers=csrf(client))

        rows = await sql(
            env, "SELECT actor, action, payload, session_id FROM audit_events ORDER BY id"
        )
        assert [r[1] for r in rows] == ["auth.login_failed", "auth.login", "auth.logout"]
        assert rows[0][0] == "anonymous"  # the attempted name is not recorded for failures
        dump = json.dumps([list(map(str, r)) for r in rows])
        secret = code.split("-", 2)[2]
        for needle in (code, secret, token, token_csrf):
            assert needle and needle not in dump


# ------------------------------------------------------------------------------ first request


async def test_a_login_as_the_very_first_request_builds_the_session_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No factory on app.state yet (fresh process): the shared lazy path creates it."""
    from cso.settings import get_settings

    async with build_env(tmp_path) as env:
        code = await mint_invite(env)
        monkeypatch.setenv("CSO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
        get_settings.cache_clear()
        try:
            del env.app.state.session_factory
            async with client_for(env) as client:
                assert (await login_as(client, code)).status_code == 200
                assert env.app.state.session_factory is not None
                assert (await client.get("/api/v1/me")).json()["role"] == "reviewer"
        finally:
            await env.app.state.engine.dispose()
            get_settings.cache_clear()

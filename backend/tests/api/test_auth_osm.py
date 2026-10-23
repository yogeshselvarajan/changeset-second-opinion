"""Sign in with OpenStreetMap (OAuth 2.0 + PKCE, scope read_prefs only)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from api_support import seed_case
from auth_support import Env, build_env, client_for, csrf, login_as, mint_invite, sql
from pydantic import SecretStr

from cso.adapters.osm.oauth import (
    AUTHORIZE_URL,
    OsmProfile,
    OsmSignInError,
    OsmTokenClient,
    code_challenge,
    new_code_verifier,
    parse_profile,
)
from cso.api.auth_core import sha256_hex
from cso.api.auth_osm import STATE_COOKIE, get_token_client
from cso.api.db import app_settings
from cso.domain.enums import Disposition
from cso.domain.models import OutcomeInput
from cso.persistence.db import session_scope
from cso.persistence.repos import OutcomesRepo
from cso.persistence.repos._common import utcnow
from cso.persistence.repos.identities_repo import IdentitiesRepo
from cso.settings import Settings

REDIRECT = "http://127.0.0.1:8000/api/v1/auth/osm/callback"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret-never-shown"  # noqa: S105 (a test value)
START = "/api/v1/auth/osm/start"
CALLBACK = "/api/v1/auth/osm/callback"


class FakeTokens(OsmTokenClient):
    """Stands in for the OSM token client; records what the callback handed it."""

    def __init__(self, profile: OsmProfile | None = None, fail: str | None = None) -> None:
        super().__init__(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_url=REDIRECT,
            user_agent="test",
        )
        self.profile = profile or OsmProfile(
            uid=4242, display_name="Mapper Mae", account_created="2020-01-02T03:04:05Z"
        )
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def profile_for_code(self, code: str, verifier: str) -> OsmProfile:
        self.calls.append((code, verifier))
        if self.fail:
            raise OsmSignInError(self.fail)
        return self.profile


def settings_with(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "osm_oauth_client_id": CLIENT_ID,
        "osm_oauth_client_secret": SecretStr(CLIENT_SECRET),
        "osm_oauth_redirect_url": REDIRECT,
    }
    values.update(overrides)
    return Settings.model_construct(**values)  # type: ignore[arg-type]


@asynccontextmanager
async def signin_env(
    tmp_path: Path, tokens: FakeTokens | None = None, **settings: object
) -> AsyncIterator[tuple[Env, httpx.AsyncClient, FakeTokens]]:
    fake = tokens or FakeTokens()
    tmp_path.mkdir(parents=True, exist_ok=True)
    async with build_env(tmp_path) as env:
        env.app.dependency_overrides[app_settings] = lambda: settings_with(**settings)
        env.app.dependency_overrides[get_token_client] = lambda: fake
        async with client_for(env, "http://127.0.0.1:8000") as client:
            yield env, client, fake


async def begin(client: httpx.AsyncClient) -> tuple[str, dict[str, list[str]]]:
    """Call start; return the state and the authorize URL's query."""
    response = await client.get(START)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return query["state"][0], query


def error_of(response: httpx.Response) -> str:
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.path == "/login"
    return parse_qs(location.query)["osm_error"][0]


# ------------------------------------------------------------------------------------- start


async def test_start_sends_the_browser_to_osm_asking_only_for_read_prefs(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, _):
        response = await client.get(START)
        assert response.status_code == 302
        target = urlsplit(response.headers["location"])
        assert f"{target.scheme}://{target.netloc}{target.path}" == AUTHORIZE_URL
        query = {k: v[0] for k, v in parse_qs(target.query).items()}
        assert query["scope"] == "read_prefs"
        assert query["response_type"] == "code"
        assert query["client_id"] == CLIENT_ID
        assert query["redirect_uri"] == REDIRECT
        assert query["code_challenge_method"] == "S256"
        assert len(query["state"]) >= 40
        assert CLIENT_SECRET not in response.headers["location"]
        assert "client_secret" not in query
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{STATE_COOKIE}={query['state']}")
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie
        rows = await sql(env, "SELECT state_hash, verifier FROM oauth_states")
        assert len(rows) == 1
        assert rows[0][0] == sha256_hex(query["state"])  # only the hash of the state is stored
        assert code_challenge(rows[0][1]) == query["code_challenge"]


async def test_start_is_not_found_when_the_feature_is_off(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        env.app.dependency_overrides[app_settings] = lambda: settings_with(osm_oauth_client_id=None)
        response = await client.get(START)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        callback = await client.get(CALLBACK, params={"code": "c", "state": "s"})
        assert callback.status_code == 404


async def test_start_is_rate_limited_per_ip(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (_, client, _fake):
        for _ in range(10):
            assert (await client.get(START)).headers["location"].startswith(AUTHORIZE_URL)
        assert error_of(await client.get(START)) == "busy"


# ---------------------------------------------------------------------------------- callback


async def test_a_good_callback_opens_a_reviewer_session_for_the_osm_account(
    tmp_path: Path,
) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        state, query = await begin(client)
        response = await client.get(CALLBACK, params={"code": "the-code", "state": state})
        assert response.status_code == 302
        assert response.headers["location"] == "/queue"
        # the verifier that went to OSM is the one whose challenge was sent in the first place
        assert [c for c, _ in fake.calls] == ["the-code"]
        assert code_challenge(fake.calls[0][1]) == query["code_challenge"][0]
        me = (await client.get("/api/v1/me")).json()
        assert me["display_name"] == "Mapper Mae"
        assert me["role"] == "reviewer" and me["via_osm"] is True
        session = await sql(
            env, "SELECT invite_code_id, identity_id, role, display_name FROM sessions"
        )
        assert len(session) == 1
        assert session[0][0] is None and session[0][1] is not None
        assert session[0][2] == "reviewer"
        identity = await sql(env, "SELECT osm_uid, display_name, account_created FROM identities")
        assert [tuple(r) for r in identity] == [(4242, "Mapper Mae", "2020-01-02T03:04:05Z")]
        audit = await sql(
            env, "SELECT actor, action FROM audit_events WHERE action = 'auth.osm_login'"
        )
        assert [tuple(r) for r in audit] == [("Mapper Mae", "auth.osm_login")]
        # the session works for a write, so CSRF is bound like any other login
        assert csrf(client)["X-CSRF"]
        assert (await client.post("/api/v1/write", headers=csrf(client))).status_code == 200


async def test_no_token_or_secret_is_stored_anywhere(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, _):
        state, _query = await begin(client)
        await client.get(CALLBACK, params={"code": "the-code", "state": state})
        for table in ("identities", "sessions", "oauth_states", "audit_events"):
            for row in await sql(env, f"SELECT * FROM {table}"):  # noqa: S608
                text = " ".join(str(v) for v in row)
                assert CLIENT_SECRET not in text and "the-code" not in text
        columns = {r[1] for r in await sql(env, "PRAGMA table_info(identities)")}
        assert not {c for c in columns if "token" in c or "secret" in c}


async def test_a_replayed_state_is_refused(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        state, _ = await begin(client)
        first = await client.get(CALLBACK, params={"code": "a", "state": state})
        assert first.headers["location"] == "/queue"
        client.cookies.clear()
        client.cookies.set(STATE_COOKIE, state, path="/api/v1/auth/osm")  # the attacker has it too
        second = await client.get(CALLBACK, params={"code": "b", "state": state})
        assert error_of(second) == "expired"
        assert len(fake.calls) == 1
        assert len(await sql(env, "SELECT id FROM sessions")) == 1


async def test_a_callback_started_in_another_browser_is_refused(tmp_path: Path) -> None:
    """Login CSRF: the attacker starts a flow, then lures the victim to the callback URL."""
    async with signin_env(tmp_path) as (env, client, fake):
        state, _ = await begin(client)
        client.cookies.clear()  # the victim's browser never saw the start request
        response = await client.get(CALLBACK, params={"code": "evil", "state": state})
        assert error_of(response) == "expired"
        assert fake.calls == []
        assert await sql(env, "SELECT id FROM sessions") == []
        assert await sql(env, "SELECT state_hash FROM oauth_states") == []  # the state is spent


async def test_a_state_that_does_not_match_the_cookie_is_refused(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        state, _ = await begin(client)
        response = await client.get(CALLBACK, params={"code": "c", "state": state + "x"})
        assert error_of(response) == "expired"
        assert fake.calls == [] and await sql(env, "SELECT id FROM sessions") == []


async def test_a_missing_state_is_refused(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        await begin(client)
        response = await client.get(CALLBACK, params={"code": "c"})
        assert error_of(response) == "expired"
        assert fake.calls == [] and await sql(env, "SELECT id FROM sessions") == []


async def test_an_unknown_state_is_refused_even_with_a_matching_cookie(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        client.cookies.set(STATE_COOKIE, "forged", path="/api/v1/auth/osm")
        response = await client.get(CALLBACK, params={"code": "c", "state": "forged"})
        assert error_of(response) == "expired"
        assert fake.calls == [] and await sql(env, "SELECT id FROM sessions") == []


async def test_an_expired_state_is_refused(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        state = "old-state"
        async with session_scope(env.factory) as db:
            await IdentitiesRepo(db).add_state(
                state_hash=sha256_hex(state),
                verifier=new_code_verifier(),
                expires_at=utcnow() - timedelta(seconds=1),
                now=utcnow() - timedelta(minutes=11),
            )
        client.cookies.set(STATE_COOKIE, state, path="/api/v1/auth/osm")
        response = await client.get(CALLBACK, params={"code": "c", "state": state})
        assert error_of(response) == "expired"
        assert fake.calls == []


async def test_a_denied_sign_in_goes_back_to_the_login_screen(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        state, _ = await begin(client)
        response = await client.get(CALLBACK, params={"error": "access_denied", "state": state})
        assert error_of(response) == "denied"
        assert fake.calls == [] and await sql(env, "SELECT id FROM sessions") == []
        assert await sql(env, "SELECT state_hash FROM oauth_states") == []


async def test_a_code_missing_from_the_callback_counts_as_denied(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (_env, client, fake):
        state, _ = await begin(client)
        assert error_of(await client.get(CALLBACK, params={"state": state})) == "denied"
        assert fake.calls == []


@pytest.mark.parametrize("reason", ["exchange_refused", "exchange_unreachable", "profile_refused"])
async def test_an_osm_failure_is_a_plain_failed_sign_in(tmp_path: Path, reason: str) -> None:
    async with signin_env(tmp_path, FakeTokens(fail=reason)) as (env, client, _):
        state, _ = await begin(client)
        response = await client.get(CALLBACK, params={"code": "c", "state": state})
        assert error_of(response) == "failed"
        assert reason not in response.headers["location"]
        assert await sql(env, "SELECT id FROM sessions") == []


async def test_the_allow_list_limits_who_can_sign_in(tmp_path: Path) -> None:
    async with signin_env(tmp_path, osm_signin_allowed_uids="1, 4242") as (_env, client, _):
        state, _ = await begin(client)
        assert (await client.get(CALLBACK, params={"code": "c", "state": state})).headers[
            "location"
        ] == "/queue"
    async with signin_env(tmp_path / "b", osm_signin_allowed_uids="1,2") as (env, client, fake):
        state, _ = await begin(client)
        response = await client.get(CALLBACK, params={"code": "c", "state": state})
        assert error_of(response) == "not_allowed"
        assert await sql(env, "SELECT id FROM sessions") == []
        assert await sql(env, "SELECT id FROM identities") == []
        del fake


CLAIM = "/api/v1/workspace/claim"


async def sign_in(client: httpx.AsyncClient) -> None:
    state, _ = await begin(client)
    await client.get(CALLBACK, params={"code": "c", "state": state})


async def test_the_named_account_claims_a_fresh_workspace_at_sign_in_and_stays_admin(
    tmp_path: Path,
) -> None:
    async with signin_env(tmp_path, bootstrap_admin_osm_uids="4242") as (env, client, _):
        await sign_in(client)
        me = (await client.get("/api/v1/me")).json()
        assert me["role"] == "admin" and me["can_claim"] is False
        audit = await sql(
            env, "SELECT action, payload FROM audit_events WHERE action = 'workspace.claimed'"
        )
        assert len(audit) == 1 and "bootstrap_env" in str(audit[0][1])
        # a later sign-in by the same account is admin straight away, with no second claim
        await sign_in(client)
        assert (await client.get("/api/v1/me")).json()["role"] == "admin"
        audit = await sql(env, "SELECT action FROM audit_events WHERE action = 'workspace.claimed'")
        assert len(audit) == 1


async def test_nobody_can_claim_when_the_operator_named_no_one(tmp_path: Path) -> None:
    """The hole this closes: a public deployment must not hand admin to whoever signs in first."""
    async with signin_env(tmp_path) as (env, client, _):
        await sign_in(client)
        me = (await client.get("/api/v1/me")).json()
        assert me["role"] == "reviewer" and me["can_claim"] is False
        refused = await client.post(CLAIM, headers=csrf(client))
        assert refused.status_code == 403
        assert (await client.get("/api/v1/me")).json()["role"] == "reviewer"
        assert await sql(env, "SELECT owner_identity_id FROM workspaces") == [(None,)]


async def test_an_account_that_is_not_named_cannot_claim(tmp_path: Path) -> None:
    async with signin_env(tmp_path, bootstrap_admin_osm_uids="1, 2") as (env, client, _):
        await sign_in(client)  # uid 4242 is not on the list
        me = (await client.get("/api/v1/me")).json()
        assert me["role"] == "reviewer" and me["can_claim"] is False
        assert (await client.post(CLAIM, headers=csrf(client))).status_code == 403
        assert await sql(env, "SELECT owner_identity_id FROM workspaces") == [(None,)]


async def test_a_named_account_that_was_signed_in_early_can_still_claim(tmp_path: Path) -> None:
    """Sign in before the operator names the account, then name it: the claim button appears."""
    async with signin_env(tmp_path) as (env, client, _):
        await sign_in(client)
        assert (await client.get("/api/v1/me")).json()["can_claim"] is False
        env.app.dependency_overrides[app_settings] = lambda: settings_with(
            bootstrap_admin_osm_uids="4242"
        )
        assert (await client.get("/api/v1/me")).json()["can_claim"] is True
        claimed = await client.post(CLAIM, headers=csrf(client))
        assert claimed.status_code == 200
        assert claimed.json()["role"] == "admin" and claimed.json()["can_claim"] is False


async def test_a_workspace_can_be_claimed_only_once(tmp_path: Path) -> None:
    async with signin_env(tmp_path, bootstrap_admin_osm_uids="4242,777") as (env, first, fake):
        await sign_in(first)
        assert (await first.get("/api/v1/me")).json()["role"] == "admin"
        fake.profile = OsmProfile(uid=777, display_name="Second Mapper", account_created=None)
        async with client_for(env, "http://127.0.0.1:8000") as second:
            await sign_in(second)
            me = (await second.get("/api/v1/me")).json()
            assert me["role"] == "reviewer" and me["can_claim"] is False
            refused = await second.post(CLAIM, headers=csrf(second))
            assert refused.status_code == 409
            assert (await second.get("/api/v1/me")).json()["role"] == "reviewer"


async def test_an_invite_session_cannot_claim_and_an_admin_invite_closes_an_open_claim(
    tmp_path: Path,
) -> None:
    async with signin_env(tmp_path, bootstrap_admin_osm_uids="4242") as (env, client, _):
        code = await mint_invite(env, role="reviewer")
        await login_as(client, code)
        assert (await client.get("/api/v1/me")).json()["can_claim"] is False
        assert (await client.post(CLAIM, headers=csrf(client))).status_code == 403
    async with signin_env(tmp_path / "b") as (env, client, _):
        await mint_invite(env, role="admin")
        await sign_in(client)
        assert (await client.get("/api/v1/me")).json()["can_claim"] is False
        assert (await client.post(CLAIM, headers=csrf(client))).status_code == 403


async def test_the_named_account_wins_even_when_an_admin_invite_exists(tmp_path: Path) -> None:
    async with signin_env(tmp_path, bootstrap_admin_osm_uids="4242") as (env, client, _):
        await mint_invite(env, role="admin")
        await sign_in(client)
        assert (await client.get("/api/v1/me")).json()["role"] == "admin"


async def test_claiming_needs_a_session(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (_env, client, _):
        assert (await client.post(CLAIM)).status_code in (401, 403)


async def test_the_web_base_url_decides_where_the_browser_lands(tmp_path: Path) -> None:
    async with signin_env(tmp_path, web_base_url="http://127.0.0.1:5173") as (_e, client, _f):
        state, _ = await begin(client)
        response = await client.get(CALLBACK, params={"code": "c", "state": state})
        assert response.headers["location"] == "http://127.0.0.1:5173/queue"
        bad, _ = await begin(client)
        failed = await client.get(CALLBACK, params={"error": "access_denied", "state": bad})
        assert failed.headers["location"] == "http://127.0.0.1:5173/login?osm_error=denied"


async def test_signing_in_again_reuses_the_identity_and_renames_it(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        state, _ = await begin(client)
        await client.get(CALLBACK, params={"code": "c", "state": state})
        fake.profile = OsmProfile(uid=4242, display_name="Mapper Mae B", account_created=None)
        state2, _ = await begin(client)
        await client.get(CALLBACK, params={"code": "c2", "state": state2})
        identities = await sql(env, "SELECT osm_uid, display_name FROM identities")
        assert [tuple(r) for r in identities] == [(4242, "Mapper Mae B")]
        sessions = await sql(env, "SELECT revoked FROM sessions ORDER BY created_at")
        assert [bool(r[0]) for r in sessions] == [True, False]  # the old session was replaced


async def test_a_signed_in_name_is_cleaned_like_any_display_name(tmp_path: Path) -> None:
    profile = OsmProfile(uid=7, display_name="  Zed​  ‮Mapper  ", account_created=None)
    async with signin_env(tmp_path, FakeTokens(profile)) as (env, client, _):
        state, _ = await begin(client)
        await client.get(CALLBACK, params={"code": "c", "state": state})
        name = (await sql(env, "SELECT display_name FROM sessions"))[0][0]
        assert "​" not in name and "‮" not in name and name == name.strip()


async def test_invite_login_still_works_beside_osm_sign_in(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, _):
        response = await login_as(client, await mint_invite(env), "invite_user")
        assert response.status_code == 200 and response.json()["me"]["via_osm"] is False
        assert response.json()["me"]["osm_signin"] is False  # login does not know the setting


async def test_me_reports_whether_the_button_should_show(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (_env, client, _):
        assert (await client.get("/api/v1/me")).json()["osm_signin"] is True
    async with signin_env(tmp_path / "off", osm_oauth_client_id=None) as (_env, client, _):
        assert (await client.get("/api/v1/me")).json()["osm_signin"] is False


async def test_an_admin_can_switch_the_workspace_sign_in_off(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, client, fake):
        state, _ = await begin(client)  # a flow that began while sign-in was still on
        assert (await client.get("/api/v1/me")).json()["osm_signin"] is True
        await sql(env, "UPDATE workspaces SET osm_signin_enabled = 0")
        assert (await client.get("/api/v1/me")).json()["osm_signin"] is False
        assert (await client.get(START)).status_code == 404
        late = await client.get(CALLBACK, params={"code": "c", "state": state})
        assert error_of(late) == "expired"
        assert fake.calls == []  # the token endpoint was never called


# --------------------------------------------------------------------------------- outcomes


async def test_an_outcome_records_the_identity_that_decided(tmp_path: Path) -> None:
    async with signin_env(tmp_path) as (env, _client, _):
        seeded = await seed_case(env.factory, 1)
        assert seeded.run_id is not None
        async with session_scope(env.factory) as db:
            identity = await IdentitiesRepo(db).upsert(
                osm_uid=9, display_name="Mapper Nia", account_created=None
            )
            identity_id = identity.id
            await OutcomesRepo(db).append(
                seeded.case_id,
                OutcomeInput(run_id_seen=seeded.run_id, disposition=Disposition.AGREE),
                reviewer_display="Mapper Nia",
                session_id=None,
                expected_version=0,
                identity_id=identity_id,
            )
        rows = await sql(env, "SELECT identity_id, reviewer_display FROM human_outcomes")
        assert len(rows) == 1 and rows[0][1] == "Mapper Nia"
        assert str(rows[0][0]).replace("-", "") == identity_id.hex


# -------------------------------------------------------------------------- pure functions


def test_pkce_challenge_matches_rfc_7636_appendix_b() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_a_new_verifier_is_a_valid_pkce_verifier() -> None:
    verifier = new_code_verifier()
    assert 43 <= len(verifier) <= 128 and verifier != new_code_verifier()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"user": None},
        {"user": {"id": "7", "display_name": "x"}},
        {"user": {"id": 0, "display_name": "x"}},
        {"user": {"id": True, "display_name": "x"}},
        {"user": {"id": 7, "display_name": "  "}},
        {"user": {"id": 7}},
    ],
)
def test_a_profile_without_an_id_and_a_name_is_unreadable(payload: object) -> None:
    with pytest.raises(OsmSignInError):
        parse_profile(payload)


def test_a_profile_keeps_only_the_id_name_and_creation_date() -> None:
    profile = parse_profile(
        {"user": {"id": 5, "display_name": " Mae ", "account_created": "2020", "home": {"lat": 1}}}
    )
    assert profile == OsmProfile(uid=5, display_name="Mae", account_created="2020")


# ----------------------------------------------------------------------------- token client


def token_client(handler: httpx.MockTransport) -> OsmTokenClient:
    return OsmTokenClient(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_url=REDIRECT,
        user_agent="agent/1",
        http=httpx.AsyncClient(transport=handler),
    )


async def test_the_token_client_posts_once_to_the_token_endpoint_then_gets_the_profile() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer"})
        return httpx.Response(200, json={"user": {"id": 3, "display_name": "Mae"}})

    profile = await token_client(httpx.MockTransport(handle)).profile_for_code("c0de", "verif")
    assert profile.uid == 3
    assert [(r.method, str(r.url)) for r in seen] == [
        ("POST", "https://www.openstreetmap.org/oauth2/token"),
        ("GET", "https://api.openstreetmap.org/api/0.6/user/details.json"),
    ]
    form = parse_qs(seen[0].content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code_verifier"] == ["verif"]
    assert form["redirect_uri"] == [REDIRECT]
    assert seen[1].headers["authorization"] == "Bearer tok"
    assert seen[0].headers["user-agent"] == "agent/1"


@pytest.mark.parametrize(
    ("token_response", "reason"),
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), "exchange_refused"),
        (httpx.Response(200, text="not json"), "exchange_unreadable"),
        (httpx.Response(200, json={"nope": 1}), "exchange_unreadable"),
        (httpx.Response(200, json=["x"]), "exchange_unreadable"),
    ],
)
async def test_a_bad_token_response_stops_before_any_profile_call(
    token_response: httpx.Response, reason: str
) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return token_response

    with pytest.raises(OsmSignInError) as caught:
        await token_client(httpx.MockTransport(handle)).profile_for_code("c", "v")
    assert caught.value.reason == reason and calls == ["POST"]


async def test_a_refused_profile_is_an_error_and_a_network_error_is_too() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(403)

    with pytest.raises(OsmSignInError) as refused:
        await token_client(httpx.MockTransport(refuse)).profile_for_code("c", "v")
    assert refused.value.reason == "profile_refused"

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(OsmSignInError) as down:
        await token_client(httpx.MockTransport(boom)).profile_for_code("c", "v")
    assert down.value.reason == "exchange_unreachable"


def test_the_token_client_never_follows_redirects_by_default() -> None:
    client = OsmTokenClient(
        client_id="a", client_secret=CLIENT_SECRET, redirect_url=REDIRECT, user_agent="u"
    )
    assert client._http.follow_redirects is False  # a redirect could carry the secret elsewhere


# --------------------------------------------------------------------------------- settings


def test_settings_enable_the_feature_only_when_all_three_values_are_set() -> None:
    assert Settings(
        osm_oauth_client_id="a",
        osm_oauth_client_secret=SecretStr("b"),
        osm_oauth_redirect_url=REDIRECT,
    ).osm_oauth_enabled
    assert not Settings(osm_oauth_client_id="a", osm_oauth_redirect_url=REDIRECT).osm_oauth_enabled
    assert not Settings().osm_oauth_enabled


def test_the_secret_is_not_printed_by_settings() -> None:
    settings = Settings(osm_oauth_client_secret=SecretStr(CLIENT_SECRET))
    assert CLIENT_SECRET not in repr(settings) and CLIENT_SECRET not in str(settings.model_dump())


def test_a_remote_http_redirect_url_is_refused() -> None:
    with pytest.raises(ValueError, match="https"):
        Settings(osm_oauth_redirect_url="http://example.org/cb")
    assert Settings(osm_oauth_redirect_url="https://example.org/cb")


def test_a_malformed_allow_list_is_refused_not_ignored() -> None:
    with pytest.raises(ValueError, match="numbers"):
        Settings(osm_signin_allowed_uids="12, abc")
    assert Settings(osm_signin_allowed_uids="12, 34").osm_signin_uids == frozenset({12, 34})
    assert Settings().osm_signin_uids == frozenset()


def test_the_bootstrap_admin_list_is_numbers_and_empty_means_nobody() -> None:
    with pytest.raises(ValueError, match="numbers"):
        Settings(bootstrap_admin_osm_uids="12, abc")
    assert Settings(bootstrap_admin_osm_uids="12, 34").bootstrap_admin_uids == frozenset({12, 34})
    # A real backend/.env on the developer's machine may name an admin; the default is nobody.
    assert Settings(_env_file=None).bootstrap_admin_uids == frozenset()


def test_the_web_base_url_must_be_an_origin() -> None:
    with pytest.raises(ValueError, match="trailing"):
        Settings(web_base_url="http://127.0.0.1:5173/")
    with pytest.raises(ValueError, match="http"):
        Settings(web_base_url="127.0.0.1:5173")

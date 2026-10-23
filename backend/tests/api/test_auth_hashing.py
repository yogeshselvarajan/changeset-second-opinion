"""Invite codes and sessions at rest: hashed, limited, expiring, revocable, race-safe."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from auth_support import build_env, client_for, login_as, make_config, mint_invite, sql

from cso.api.auth_core import (
    InviteHasher,
    create_invite,
    generate_invite_code,
    parse_invite_code,
    sha256_hex,
)
from cso.persistence.db import session_scope
from cso.persistence.repos._common import utcnow
from cso.persistence.repos.sessions_repo import SessionsRepo


async def test_database_holds_only_hashes_never_the_plaintext(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        code = await mint_invite(env, label="for-anna")
        await login_as(client, code, "mapper_a")
        token, csrf_token = client.cookies.get("cso_session"), client.cookies.get("cso_csrf")
        secret = code.split("-", 2)[2]

        invite = (await sql(env, "SELECT code_hash, code_id, label FROM invite_codes"))[0]
        assert invite[0].startswith("$argon2id$")
        assert invite[1] == code.split("-")[1]  # the public id is searchable by design
        session = (await sql(env, "SELECT token_hash, csrf_hash FROM sessions"))[0]
        assert session[0] == sha256_hex(token or "") and session[1] == sha256_hex(csrf_token or "")

        everything = ""
        for table in ("invite_codes", "sessions", "audit_events"):
            query = f"SELECT * FROM {table}"  # noqa: S608
            everything += repr(await sql(env, query))
        for needle in (code, secret, token, csrf_token):
            assert needle and needle not in everything


def test_codes_have_enough_entropy_and_round_trip() -> None:
    code, code_id, secret = generate_invite_code()
    assert parse_invite_code(code) == (code_id, secret)
    assert len(secret) >= 32  # 192 bits
    assert generate_invite_code()[0] != code
    assert parse_invite_code("  " + code + "\n") == (code_id, secret)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "cso-",
        "cso-zzzzzzzz-" + "a" * 32,
        "cso-12345678-short",
        "xxx-12345678-" + "a" * 32,
        "cso-12345678-" + "a" * 31,
        "cso-12345678-" + "a" * 33,
        "cso-12345678-" + "!" * 32,
    ],
)
def test_malformed_codes_do_not_parse(bad: str) -> None:
    assert parse_invite_code(bad) is None


async def test_hasher_accepts_the_secret_rejects_others_and_tolerates_garbage_hashes() -> None:
    hasher = InviteHasher(make_config())
    stored = await hasher.hash("s3cret")
    assert await hasher.verify(stored, "s3cret")
    assert not await hasher.verify(stored, "other")
    assert not await hasher.verify("not-a-hash", "s3cret")
    assert not await hasher.verify("", "s3cret")
    assert stored != await hasher.hash("s3cret")  # salted


async def test_create_invite_validates_its_arguments(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        async with session_scope(env.factory) as db:
            with pytest.raises(ValueError, match="role"):
                await create_invite(db, env.hasher, role="superuser")
            with pytest.raises(ValueError, match="max_uses"):
                await create_invite(db, env.hasher, role="reviewer", max_uses=0)


async def test_a_single_use_invite_works_once(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        code = await mint_invite(env, max_uses=1)
        async with client_for(env) as first, client_for(env) as second:
            assert (await login_as(first, code)).status_code == 200
            assert (await login_as(second, code)).status_code == 401


async def test_a_multi_use_invite_stops_after_its_limit(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        code = await mint_invite(env, max_uses=2)
        statuses = []
        for _ in range(3):
            async with client_for(env) as client:
                statuses.append((await login_as(client, code)).status_code)
        assert statuses == [200, 200, 401]
        assert (await sql(env, "SELECT use_count FROM invite_codes"))[0][0] == 2


async def test_an_unlimited_invite_keeps_working(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        code = await mint_invite(env)
        for _ in range(4):
            async with client_for(env) as client:
                assert (await login_as(client, code)).status_code == 200


async def test_an_expired_invite_is_refused_and_a_live_one_is_accepted(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        expired = await mint_invite(env, ttl=timedelta(seconds=-5))
        live = await mint_invite(env, ttl=timedelta(hours=1))
        async with client_for(env) as client:
            assert (await login_as(client, expired)).status_code == 401
            assert (await login_as(client, live)).status_code == 200


async def test_a_disabled_invite_is_refused_and_revoking_it_ends_its_sessions(
    tmp_path: Path,
) -> None:
    async with build_env(tmp_path) as env:
        code = await mint_invite(env)
        async with client_for(env) as client:
            assert (await login_as(client, code)).status_code == 200
            assert (await client.get("/api/v1/me")).json()["role"] == "reviewer"
            invite_id = (await sql(env, "SELECT id FROM invite_codes"))[0][0]
            async with session_scope(env.factory) as db:
                repo = SessionsRepo(db)
                invite = await repo.get_invite_by_code_id(code.split("-")[1])
                assert invite is not None
                assert await repo.disable_invite(invite.id)
                assert await repo.revoke_for_invite(invite.id) == 1
            assert invite_id is not None
            assert (await client.get("/api/v1/me")).json()["role"] == "viewer"
        async with client_for(env) as again:
            assert (await login_as(again, code)).status_code == 401


async def test_two_logins_racing_for_the_last_use_cannot_both_win(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        code = await mint_invite(env, max_uses=1)

        async def attempt() -> int:
            async with client_for(env) as client:
                return (await login_as(client, code)).status_code

        results = await asyncio.gather(*(attempt() for _ in range(4)))
        assert sorted(results) == [200, 401, 401, 401]
        assert (await sql(env, "SELECT use_count FROM invite_codes"))[0][0] == 1


async def test_consume_invite_is_atomic_at_the_repository_level(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        await mint_invite(env, max_uses=1)
        invite_id = (await sql(env, "SELECT id FROM invite_codes"))[0][0]
        from uuid import UUID

        async def consume() -> bool:
            async with session_scope(env.factory) as db:
                return await SessionsRepo(db).consume_invite(UUID(invite_id))

        outcomes = await asyncio.gather(*(consume() for _ in range(5)))
        assert outcomes.count(True) == 1


async def test_sessions_repo_idle_and_touch_rules(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env:
        now = utcnow()
        async with session_scope(env.factory) as db:
            repo = SessionsRepo(db)
            invite = await repo.add_invite_code(code_hash="h", role="reviewer", code_id="aaaaaaaa")
            row = await repo.create_session(
                invite_code_id=invite.id,
                display_name="x",
                role="reviewer",
                expires_at=now + timedelta(hours=12),
                token_hash="t1",  # noqa: S106
                csrf_hash="c1",
                now=now,
            )
            assert await repo.get_active_by_token_hash("t1", now=now) is not None
            assert await repo.get_active_by_token_hash(
                "t1", now=now, idle_timeout=timedelta(hours=1)
            )
            later = now + timedelta(hours=3)
            assert (
                await repo.get_active_by_token_hash(
                    "t1", now=later, idle_timeout=timedelta(hours=1)
                )
                is None
            )
            assert await repo.get_active_by_token_hash("t1", now=later) is not None  # no idle rule
            assert await repo.touch(row, now=now + timedelta(seconds=5)) is False  # too soon
            assert await repo.touch(row, now=now + timedelta(minutes=5)) is True
            assert await repo.get_active_by_token_hash("t1", now=now + timedelta(hours=13)) is None
            assert await repo.get_active_by_token_hash("missing", now=now) is None

"""Readiness: database reachable, migrations at head, model server probe, /readyz states."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from conftest import migrate_stamp
from cso.api.db import app_settings
from cso.api.schemas import DeciderHealth
from cso.observability.readiness import (
    check_database,
    head_revision,
    make_decider_probe,
)
from cso.persistence.db import make_engine, make_sessionmaker
from cso.persistence.tables import Base
from cso.settings import Settings

LIVE = Settings(mode="live", user_agent="CSO/0.1 (+https://example.org/cso; ops@example.org)")


async def bare_factory(tmp_path: Path, name: str, *, revision: str | None, tables: bool = True):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    if tables:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    await migrate_stamp(engine, revision)
    return engine, make_sessionmaker(engine)


# --------------------------------------------------------------------------- database


def test_head_revision_is_the_latest_shipped_migration() -> None:
    assert head_revision() is not None and head_revision() >= "0003"


async def test_database_at_head_is_ready(factory) -> None:
    result = await check_database(factory)
    assert result.reachable and result.at_head and result.ok


async def test_database_with_old_migrations_is_not_ready(tmp_path: Path) -> None:
    engine, factory = await bare_factory(tmp_path, "old.db", revision="0001")
    try:
        result = await check_database(factory)
    finally:
        await engine.dispose()
    assert result.reachable and not result.at_head and not result.ok


async def test_database_that_was_never_migrated_is_not_ready(tmp_path: Path) -> None:
    engine, factory = await bare_factory(tmp_path, "fresh.db", revision=None, tables=False)
    try:
        result = await check_database(factory)
    finally:
        await engine.dispose()
    assert result.reachable and not result.at_head


async def test_unreachable_database_is_reported_as_down(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'missing-dir' / 'x.db'}")
    try:
        result = await check_database(make_sessionmaker(engine))
    finally:
        await engine.dispose()
    assert not result.reachable and not result.at_head and not result.ok


# --------------------------------------------------------------------------- model server probe


def probe_with(handler) -> object:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return make_decider_probe("http://decider:8099/", client=client)


async def test_probe_reads_identity_from_a_healthy_server() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200, json={"status": "ok", "model": "m", "checkpoint": "org/ckpt", "device": "cuda"}
        )

    health = await probe_with(handler)()
    assert health == DeciderHealth(ok=True, model="m", checkpoint="org/ckpt", device="cuda")
    assert seen == ["http://decider:8099/health"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"status": "loading"}),
        httpx.Response(200, json={"status": "starting"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["status", "ok"]),
    ],
)
async def test_probe_reports_a_server_that_is_not_ok(response: httpx.Response) -> None:
    assert (await probe_with(lambda request: response)()).ok is False


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
async def test_probe_never_raises_on_network_errors(error: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    assert (await probe_with(handler)()).ok is False


async def test_probe_ignores_non_string_identity_fields() -> None:
    body = {"status": "ok", "model": 5, "checkpoint": None, "device": ["x"]}
    health = await probe_with(lambda request: httpx.Response(200, json=body))()
    assert health == DeciderHealth(ok=True)


# --------------------------------------------------------------------------- /readyz


def ok_probe():
    async def probe() -> DeciderHealth:
        return DeciderHealth(ok=True, model="m", checkpoint="c", device="cpu")

    return probe


def failing_probe():
    async def probe() -> DeciderHealth:
        return DeciderHealth(ok=False)

    return probe


async def test_replay_is_ready_without_a_model_server(client) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["db"] is True and response.json()["decider"]["ok"] is False


async def test_live_is_ready_when_the_database_and_model_server_are_healthy(app, client) -> None:
    app.dependency_overrides[app_settings] = lambda: LIVE
    app.state.decider_probe = ok_probe()
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["decider"] == {
        "ok": True,
        "model": "m",
        "checkpoint": "c",
        "device": "cpu",
    }


async def test_live_returns_503_when_the_decider_check_fails(app, client) -> None:
    app.dependency_overrides[app_settings] = lambda: LIVE
    app.state.decider_probe = failing_probe()
    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["db"] is True and body["decider"]["ok"] is False and body["request_id"]


async def test_live_returns_503_when_no_probe_is_configured(app, client) -> None:
    app.dependency_overrides[app_settings] = lambda: LIVE
    assert (await client.get("/readyz")).status_code == 503


async def test_a_probe_that_raises_counts_as_down(app, client) -> None:
    async def explode() -> DeciderHealth:
        raise RuntimeError("boom")

    app.dependency_overrides[app_settings] = lambda: LIVE
    app.state.decider_probe = explode
    assert (await client.get("/readyz")).status_code == 503


async def test_the_probe_result_is_cached_between_requests(app, client) -> None:
    calls: list[int] = []

    async def counting() -> DeciderHealth:
        calls.append(1)
        return DeciderHealth(ok=True)

    app.dependency_overrides[app_settings] = lambda: LIVE
    app.state.decider_probe = counting
    for _ in range(3):
        assert (await client.get("/readyz")).status_code == 200
    assert len(calls) == 1


async def test_readyz_is_503_with_reasons_when_migrations_are_behind(
    app, client, tmp_path: Path
) -> None:
    engine, factory = await bare_factory(tmp_path, "behind.db", revision="0001")
    app.state.session_factory = factory
    try:
        response = await client.get("/readyz")
    finally:
        await engine.dispose()
    body = response.json()
    assert response.status_code == 503
    assert body["db"] is False and body["db_reachable"] is True
    assert body["migrations_at_head"] is False


async def test_readyz_is_503_when_the_database_is_down(app, client, tmp_path: Path) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'gone' / 'x.db'}")
    app.state.session_factory = make_sessionmaker(engine)
    try:
        response = await client.get("/readyz")
    finally:
        await engine.dispose()
    body = response.json()
    assert response.status_code == 503 and body["db_reachable"] is False

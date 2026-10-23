"""Application wiring: middleware order, lifespan probe and logging, shutdown disposal."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import structlog

from cso.api.schemas import DeciderHealth
from cso.api.security import SecurityMiddleware
from cso.main import create_app
from cso.observability import RequestContextMiddleware
from cso.observability import logging as obs_logging
from cso.settings import get_settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Replay mode on a temporary database, no embedded worker, settings cache cleared."""
    monkeypatch.setenv("CSO_MODE", "replay")
    monkeypatch.setenv("CSO_JOBS_WORKER_ENABLED", "false")
    monkeypatch.setenv("CSO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'wired.db'}")
    monkeypatch.delenv("CSO_DECIDER_URL", raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()
    structlog.reset_defaults()
    obs_logging._configured = None


def test_request_context_is_the_outermost_middleware_and_security_sits_inside_it() -> None:
    order = [m.cls for m in create_app().user_middleware]
    assert order[0] is RequestContextMiddleware
    assert SecurityMiddleware in order and order.index(SecurityMiddleware) > 0


async def test_lifespan_configures_logging_from_the_settings(env) -> None:
    app = create_app()
    assert obs_logging._configured is None
    async with app.router.lifespan_context(app):
        assert obs_logging._configured == ("console", "INFO")


async def test_live_mode_logs_json(env) -> None:
    env.setenv("CSO_MODE", "live")
    env.setenv("CSO_USER_AGENT", "CSO/0.1 (+https://example.org/cso; ops@example.org)")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        assert obs_logging._configured == ("json", "INFO")


async def test_no_probe_is_installed_without_a_decider_url(env) -> None:
    app = create_app()
    async with app.router.lifespan_context(app):
        assert getattr(app.state, "decider_probe", None) is None


async def test_a_probe_is_installed_when_a_decider_url_is_configured_and_closed_after(
    env,
) -> None:
    env.setenv("CSO_DECIDER_URL", "http://decider.invalid:8099")
    get_settings.cache_clear()
    closed: list[int] = []
    real_aclose = httpx.AsyncClient.aclose

    async def counting_aclose(self: httpx.AsyncClient) -> None:
        closed.append(1)
        await real_aclose(self)

    env.setattr(httpx.AsyncClient, "aclose", counting_aclose)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert callable(app.state.decider_probe)
        assert closed == []
    assert closed == [1]


async def test_a_probe_set_by_the_caller_is_not_replaced(env) -> None:
    env.setenv("CSO_DECIDER_URL", "http://decider.invalid:8099")
    get_settings.cache_clear()

    async def mine() -> DeciderHealth:
        return DeciderHealth(ok=True)

    app = create_app()
    app.state.decider_probe = mine
    async with app.router.lifespan_context(app):
        assert app.state.decider_probe is mine


async def test_shutdown_disposes_the_session_factory(env) -> None:
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/readyz")  # first use builds the engine and session factory
        assert app.state.engine is not None and app.state.session_factory is not None
    assert app.state.engine is None and app.state.session_factory is None


async def test_shutdown_without_any_database_use_is_a_no_op(env) -> None:
    app = create_app()
    async with app.router.lifespan_context(app):
        pass
    assert getattr(app.state, "engine", None) is None


async def test_lifespan_logs_start_and_stop_as_json_lines_in_live_mode(env, capsys) -> None:
    import json

    env.setenv("CSO_MODE", "live")
    env.setenv("CSO_USER_AGENT", "CSO/0.1 (+https://example.org/cso; ops@example.org)")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        pass
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    events = [line["event"] for line in lines]
    assert events == ["app.started", "app.stopped"]
    assert lines[0]["mode"] == "live" and lines[0]["worker"] is False

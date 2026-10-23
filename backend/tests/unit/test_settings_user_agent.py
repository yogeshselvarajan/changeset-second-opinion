from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from cso.main import create_app
from cso.settings import DEFAULT_USER_AGENT, Settings, SettingsError, get_settings

REAL_UA = "ChangesetSecondOpinion/0.1 (+https://example.org/cso-repo; maintainer@example.org)"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    for name in ("CSO_MODE", "CSO_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_default_user_agent_is_the_documented_placeholder_string() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.user_agent == DEFAULT_USER_AGENT
    assert DEFAULT_USER_AGENT == "ChangesetSecondOpinion/0.1 (+<REPO_URL>; <CONTACT_EMAIL>)"
    assert settings.user_agent_is_placeholder
    assert settings.mode == "replay"


def test_replay_mode_starts_with_the_placeholder() -> None:
    settings = Settings(_env_file=None, mode="replay")  # type: ignore[call-arg]
    assert settings.user_agent_is_placeholder  # allowed offline


@pytest.mark.parametrize(
    "user_agent",
    [
        DEFAULT_USER_AGENT,
        "ChangesetSecondOpinion/0.1 (+<REPO_URL>; real@example.org)",
        "ChangesetSecondOpinion/0.1 (+https://example.org/repo; <CONTACT_EMAIL>)",
        "changeset-second-opinion/0.1 (+https://github.com/changeset-second-opinion)",
    ],
)
def test_live_mode_refuses_any_placeholder_user_agent(user_agent: str) -> None:
    with pytest.raises(ValidationError, match="CSO_USER_AGENT"):
        Settings(_env_file=None, mode="live", user_agent=user_agent)  # type: ignore[call-arg]


def test_live_mode_accepts_a_real_user_agent() -> None:
    settings = Settings(_env_file=None, mode="live", user_agent=REAL_UA)  # type: ignore[call-arg]
    assert not settings.user_agent_is_placeholder
    settings.require_real_user_agent()


def test_require_real_user_agent_raises_a_settings_error_in_replay_mode() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(SettingsError, match="placeholder"):
        settings.require_real_user_agent()


def test_environment_variables_drive_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSO_MODE", "live")
    monkeypatch.setenv("CSO_USER_AGENT", DEFAULT_USER_AGENT)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("CSO_USER_AGENT", REAL_UA)
    assert Settings(_env_file=None).mode == "live"  # type: ignore[call-arg]


async def test_live_app_fails_startup_with_a_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSO_MODE", "live")
    monkeypatch.setenv("CSO_USER_AGENT", DEFAULT_USER_AGENT)
    app = create_app()
    with pytest.raises(ValidationError, match="CSO_USER_AGENT"):
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover


async def test_replay_app_still_starts_and_serves_healthz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSO_MODE", "replay")
    monkeypatch.setenv("CSO_USER_AGENT", DEFAULT_USER_AGENT)
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/healthz")).json() == {"status": "ok"}


async def test_live_app_starts_with_a_real_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSO_MODE", "live")
    monkeypatch.setenv("CSO_USER_AGENT", REAL_UA)
    app = create_app()
    async with app.router.lifespan_context(app):
        pass

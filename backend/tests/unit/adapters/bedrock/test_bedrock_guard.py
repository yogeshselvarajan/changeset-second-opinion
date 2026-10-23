"""No Bedrock client exists unless live mode AND CSO_LIVE_BEDROCK=1; all else is offline."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from cso.adapters.bedrock import BedrockDrafter, build_drafter, live_bedrock_enabled
from cso.adapters.bedrock import client as client_module
from cso.settings import Settings

REAL_UA = "ChangesetSecondOpinion/0.1 (+https://example.org/repo; someone@example.org)"
LIVE = Settings(mode="live", user_agent=REAL_UA)
REPLAY = Settings(mode="replay", user_agent=REAL_UA)


class LoaderSpy:
    """Replaces `importlib` inside the client module and records every module it is asked for."""

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.clients: list[dict[str, Any]] = []
        self.configs: list[dict[str, Any]] = []
        spy = self

        class Config:
            def __init__(self, **kwargs: Any) -> None:
                spy.configs.append(kwargs)
                self.kwargs = kwargs

        self._modules = {
            "boto3": SimpleNamespace(client=self._client),
            "botocore.config": SimpleNamespace(Config=Config),
        }

    def _client(self, service: str, **kwargs: Any) -> object:
        self.clients.append({"service": service, **kwargs})
        return SimpleNamespace(converse=lambda **_: {})

    def import_module(self, name: str) -> Any:
        self.requested.append(name)
        return self._modules[name]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> LoaderSpy:
    loader = LoaderSpy()
    monkeypatch.setattr(
        client_module, "importlib", SimpleNamespace(import_module=loader.import_module)
    )
    return loader


@pytest.mark.parametrize(
    ("settings", "flag", "expected"),
    [
        (LIVE, "1", True),
        (LIVE, None, False),
        (LIVE, "0", False),
        (LIVE, "", False),
        (LIVE, "true", False),
        (LIVE, "yes", False),
        (REPLAY, "1", False),
        (REPLAY, None, False),
    ],
)
def test_the_live_gate_needs_live_mode_and_the_flag_set_to_exactly_one(
    settings: Settings, flag: str | None, expected: bool
) -> None:
    env = {} if flag is None else {"CSO_LIVE_BEDROCK": flag}
    assert live_bedrock_enabled(settings, env) is expected


@pytest.mark.parametrize(
    ("settings", "env"),
    [
        (REPLAY, {}),
        (REPLAY, {"CSO_LIVE_BEDROCK": "1"}),
        (LIVE, {}),
        (LIVE, {"CSO_LIVE_BEDROCK": "0"}),
        (LIVE, {"CSO_LIVE_BEDROCK": "true"}),
    ],
)
def test_no_client_is_built_and_boto3_is_never_loaded_unless_both_conditions_hold(
    spy: LoaderSpy, settings: Settings, env: dict[str, str]
) -> None:
    assert build_drafter(settings, env) is None
    assert spy.requested == [] and spy.clients == []


def test_with_both_conditions_exactly_one_client_is_built_with_the_project_timeouts(
    spy: LoaderSpy,
) -> None:
    drafter = build_drafter(
        Settings(mode="live", user_agent=REAL_UA, bedrock_region="eu-west-1"),
        {"CSO_LIVE_BEDROCK": "1"},
    )
    assert isinstance(drafter, BedrockDrafter)
    assert drafter.model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert len(spy.clients) == 1
    assert spy.clients[0]["service"] == "bedrock-runtime"
    assert spy.clients[0]["region_name"] == "eu-west-1"
    assert spy.configs == [
        {
            "connect_timeout": 3,
            "read_timeout": 20,
            "retries": {"mode": "standard", "max_attempts": 1},
        }
    ]


def test_importing_the_adapter_package_does_not_load_boto3() -> None:
    code = (
        "import sys, cso.adapters.bedrock, cso.domain.draft_validation, cso.domain.templates;"
        "print('boto3' in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# ----------------------------------------------------------------------------- the agent model


def test_the_agent_model_is_always_the_scripted_one_so_no_agent_call_bypasses_metering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-M1: even live mode with CSO_LIVE_BEDROCK=1 never builds a Bedrock-backed agent model."""
    from cso.agent import ScriptedToolModel, build_agent_model
    from cso.domain.enums import Response

    created: list[dict[str, Any]] = []

    class BedrockModelSpy:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr("strands.models.BedrockModel", BedrockModelSpy, raising=False)

    for flag in (None, "1"):
        monkeypatch.delenv("CSO_LIVE_BEDROCK", raising=False)
        if flag:
            monkeypatch.setenv("CSO_LIVE_BEDROCK", flag)
        for settings in (REPLAY, LIVE):
            assert isinstance(
                build_agent_model(settings, Response.WELCOME_AND_TIPS), ScriptedToolModel
            )
    assert created == []


def test_the_default_job_dependencies_are_offline(
    spy: LoaderSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cso.jobs.deps import build_drafting_deps

    monkeypatch.delenv("CSO_LIVE_BEDROCK", raising=False)
    deps = build_drafting_deps(REPLAY)
    assert deps.drafter is None and deps.budget is not None
    assert spy.requested == [] and spy.clients == []

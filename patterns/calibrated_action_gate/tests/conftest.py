"""Shared fixtures: a real recorded request/response/health from a GPU Decider (synthetic case)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from calibrated_action_gate import ChoiceSpec, NoulSpec, RequestPlan, build_request

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def recorded_request() -> dict[str, Any]:
    return load("systemone_request_02.json")


@pytest.fixture
def recorded_response() -> dict[str, Any]:
    return load("systemone_response_02.json")


@pytest.fixture
def recorded_health() -> dict[str, Any]:
    return load("health.json")


@pytest.fixture
def specs(recorded_request: dict[str, Any]) -> tuple[list[ChoiceSpec], list[NoulSpec]]:
    """The specs that reproduce the recorded request (base order is the `_p0` order)."""
    q = recorded_request["questions"]
    choices = [
        ChoiceSpec("nature", q["nature_p0"]["instructions"], q["nature_p0"]["criteria"]),
        ChoiceSpec("response", q["response_p0"]["instructions"], q["response_p0"]["criteria"]),
    ]
    nouls = [
        NoulSpec(n, q[n]["instructions"])
        for n in ("comment_matches_changes", "mature_feature_deleted_probe")
    ]
    return choices, nouls


@pytest.fixture
def plan(
    recorded_request: dict[str, Any], specs: tuple[list[ChoiceSpec], list[NoulSpec]]
) -> RequestPlan:
    choices, nouls = specs
    return build_request(recorded_request["state"], choices, nouls)


@pytest.fixture
def mutable_response(recorded_response: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(recorded_response)

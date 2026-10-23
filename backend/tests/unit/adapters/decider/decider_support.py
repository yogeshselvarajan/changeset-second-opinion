"""Shared helpers for the Decider tests: recorded real fixtures and a fake server."""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from cso.domain.config import CommunityConfig

REPO = Path(__file__).resolve().parents[5]
PATTERN_SRC = REPO / "patterns" / "calibrated_action_gate" / "src"
FIXTURES = REPO / "patterns" / "calibrated_action_gate" / "tests" / "fixtures"
BASE = "http://decider.test"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def recorded_request() -> dict[str, Any]:
    return load("systemone_request_02.json")


def recorded_response() -> dict[str, Any]:
    return copy.deepcopy(load("systemone_response_02.json"))


def recorded_health() -> dict[str, Any]:
    return load("health.json")


def config() -> CommunityConfig:
    return CommunityConfig.load()


Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def client_for(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler))


def fake_server(
    response: dict[str, Any] | None = None, health: dict[str, Any] | None = None
) -> Handler:
    """Serve `/health` and `/v1/systemone` from recorded (or given) payloads."""
    resp = recorded_response() if response is None else response
    hlth = recorded_health() if health is None else health

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json=hlth)
        return httpx.Response(200, json=resp)

    return handler

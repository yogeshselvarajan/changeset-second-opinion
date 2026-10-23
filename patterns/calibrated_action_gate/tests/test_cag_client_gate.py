from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from calibrated_action_gate import (
    AsyncDeciderClient,
    ChoiceSpec,
    DeciderClient,
    DeciderUnavailable,
    NoulSpec,
    SchemaError,
    StateTooLong,
    adecide,
    decide,
)

BASE = "http://decider.test"


def server(
    response: dict[str, Any], health: dict[str, Any], calls: list[str] | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/health":
            return httpx.Response(200, json=health)
        assert request.url.path == "/v1/systemone"
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handler)


def test_decide_end_to_end_with_the_recorded_response(
    specs: tuple[list[ChoiceSpec], list[NoulSpec]],
    recorded_request: dict[str, Any],
    recorded_response: dict[str, Any],
    recorded_health: dict[str, Any],
) -> None:
    calls: list[str] = []
    client = DeciderClient(BASE, transport=server(recorded_response, recorded_health, calls))
    result = decide(client, recorded_request["state"], *specs)
    assert calls == ["GET /health", "POST /v1/systemone"]
    assert set(result.aggregates) == {"nature", "response"}
    nature = result.aggregates["nature"]
    assert nature.argmax in specs[0][0].criteria
    # the server rounds to 4 decimals, so sums stay within the contract tolerance, not exactly 1
    assert sum(nature.probabilities.values()) == pytest.approx(1, abs=1e-3)
    receipt = result.receipt.to_dict()
    assert receipt["decider"]["device"] == "cuda"
    assert receipt["state_tokens"] == recorded_response["usage"]["input_tokens"]
    assert len(receipt["permutations"]) == 6
    assert set(receipt["nouls"]) == {"comment_matches_changes", "mature_feature_deleted_probe"}
    assert result.receipt.to_json() == result.receipt.to_json()
    assert json.loads(result.receipt.to_json()) == receipt


def test_async_decide_matches_sync(
    specs: tuple[list[ChoiceSpec], list[NoulSpec]],
    recorded_request: dict[str, Any],
    recorded_response: dict[str, Any],
    recorded_health: dict[str, Any],
) -> None:
    sync = decide(
        DeciderClient(BASE, transport=server(recorded_response, recorded_health)),
        recorded_request["state"],
        *specs,
    )

    async def run() -> Any:
        client = AsyncDeciderClient(BASE, transport=server(recorded_response, recorded_health))
        try:
            return await adecide(client, recorded_request["state"], *specs)
        finally:
            await client.aclose()

    other = asyncio.run(run())
    assert other.aggregates == sync.aggregates
    assert other.nouls == sync.nouls


def test_schema_deviation_raises_with_the_raw_response(
    specs: tuple[list[ChoiceSpec], list[NoulSpec]],
    recorded_response: dict[str, Any],
    recorded_health: dict[str, Any],
) -> None:
    recorded_response["answers"]["nature_p0"]["confidence"] = 7
    client = DeciderClient(BASE, transport=server(recorded_response, recorded_health))
    with pytest.raises(SchemaError) as info:
        decide(client, "state", *specs)
    assert info.value.raw["answers"]["nature_p0"]["confidence"] == 7


def test_connection_error_is_retried_once_then_reported() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    client = DeciderClient(BASE, transport=httpx.MockTransport(handler))
    with pytest.raises(DeciderUnavailable):
        client.health()
    assert attempts == 2


def test_connection_error_then_success_recovers(recorded_health: dict[str, Any]) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=recorded_health)

    client = DeciderClient(BASE, transport=httpx.MockTransport(handler))
    assert client.health()["device"] == "cuda"
    assert attempts == 2


def test_422_is_never_retried_and_maps_to_state_too_long() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(422, json={"detail": "state exceeds max_length"})

    client = DeciderClient(BASE, transport=httpx.MockTransport(handler))
    with pytest.raises(StateTooLong):
        client.systemone({"state": "x", "questions": {}})
    assert attempts == 1


def test_timeouts_and_server_errors_are_not_retried() -> None:
    attempts = 0

    def timeout(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DeciderUnavailable):
        DeciderClient(BASE, transport=httpx.MockTransport(timeout)).health()
    assert attempts == 1
    boom = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(DeciderUnavailable, match="500"):
        DeciderClient(BASE, transport=boom).health()
    notjson = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(DeciderUnavailable, match="non-JSON"):
        DeciderClient(BASE, transport=notjson).health()

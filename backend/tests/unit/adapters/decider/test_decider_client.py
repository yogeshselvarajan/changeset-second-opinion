from __future__ import annotations

import anyio
import httpx
import pytest
from decider_support import client_for, config, fake_server, recorded_health, recorded_response

from cso.adapters.decider import (
    CPU_TIMEOUT_S,
    GPU_TIMEOUT_S,
    DeciderBusy,
    DeciderClient,
    DeciderSchemaError,
    DeciderStateTooLong,
    DeciderTimeout,
    DeciderUnavailable,
    SingleFlightGate,
)
from cso.settings import Settings


async def test_decide_returns_validated_aggregated_outputs_and_identity() -> None:
    client = DeciderClient("unused", http=client_for(fake_server()))
    result = await client.decide("rendered evidence", config())
    assert result.identity.device == "cuda"
    assert result.identity.max_length == 4096
    assert result.outputs.nature.argmax in result.outputs.nature.probabilities
    assert len(result.outputs.permutations) == 6
    assert result.input_tokens == recorded_response()["usage"]["input_tokens"]
    assert result.server_latency_ms == recorded_response()["latency_ms"]
    assert result.questions_hash.startswith("sha256:")


async def test_ten_concurrent_calls_never_overlap() -> None:
    active = 0
    peak = 0
    served = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak, served
        if request.url.path == "/health":
            return httpx.Response(200, json=recorded_health())
        active += 1
        peak = max(peak, active)
        await anyio.sleep(0.01)
        active -= 1
        served += 1
        return httpx.Response(200, json=recorded_response())

    client = DeciderClient("unused", http=client_for(handler))
    cfg = config()
    async with anyio.create_task_group() as tg:
        for i in range(10):
            tg.start_soon(client.decide, f"state {i}", cfg)
    assert served == 10
    assert peak == 1


async def test_422_maps_to_state_too_long_and_is_never_retried() -> None:
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.url.path == "/health":
            return httpx.Response(200, json=recorded_health())
        posts += 1
        return httpx.Response(422, json={"detail": "state exceeds max_length"})

    client = DeciderClient("unused", http=client_for(handler))
    with pytest.raises(DeciderStateTooLong) as info:
        await client.decide("too long", config())
    assert info.value.failure_code == "state_too_long"
    assert posts == 1


async def test_connection_error_is_retried_once() -> None:
    attempts = 0

    async def always_down(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    client = DeciderClient("unused", http=client_for(always_down))
    with pytest.raises(DeciderUnavailable) as info:
        await client.decide("s", config())
    assert attempts == 2
    assert info.value.failure_code == "decider_unavailable"

    attempts = 0

    async def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("refused", request=request)
        return await fake_server()(request)

    client = DeciderClient("unused", http=client_for(flaky))
    assert (await client.decide("s", config())).identity.model
    assert attempts == 3  # one failed health, one health retry, one systemone


async def test_timeouts_are_typed_and_not_retried() -> None:
    attempts = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    client = DeciderClient("unused", http=client_for(slow))
    with pytest.raises(DeciderTimeout):
        await client.decide("s", config())
    assert attempts == 1


async def test_server_errors_and_non_json_are_typed() -> None:
    async def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(DeciderUnavailable, match="500"):
        await DeciderClient("unused", http=client_for(boom)).decide("s", config())

    async def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    with pytest.raises(DeciderSchemaError, match="not JSON"):
        await DeciderClient("unused", http=client_for(html)).decide("s", config())


async def test_schema_deviation_raises_with_the_raw_response_and_no_default() -> None:
    bad = recorded_response()
    bad["answers"]["nature_p0"]["confidence"] = 7
    client = DeciderClient("unused", http=client_for(fake_server(response=bad)))
    with pytest.raises(DeciderSchemaError) as info:
        await client.decide("s", config())
    assert info.value.raw["answers"]["nature_p0"]["confidence"] == 7
    assert info.value.failure_code == "schema"


async def test_malformed_health_is_a_schema_error() -> None:
    client = DeciderClient("unused", http=client_for(fake_server(health={"status": "ok"})))
    with pytest.raises(DeciderSchemaError, match="health"):
        await client.decide("s", config())


def test_from_settings_picks_the_timeout_and_requires_a_url() -> None:
    gpu = DeciderClient.from_settings(Settings(decider_url="http://127.0.0.1:8099"))
    cpu = DeciderClient.from_settings(
        Settings(decider_url="http://127.0.0.1:8099"), device_class="cpu"
    )
    assert gpu._http.timeout.read == GPU_TIMEOUT_S == 45
    assert cpu._http.timeout.read == CPU_TIMEOUT_S == 90
    with pytest.raises(ValueError, match="CSO_DECIDER_URL"):
        DeciderClient.from_settings(Settings(decider_url=None))


async def test_a_full_queue_rejects_the_oldest_waiter() -> None:
    gate = SingleFlightGate(max_waiting=2)
    await gate.acquire()  # holder
    outcomes: dict[str, str] = {}

    async def wait(name: str) -> None:
        try:
            await gate.acquire()
        except DeciderBusy:
            outcomes[name] = "busy"
            return
        outcomes[name] = "ran"
        gate.release()

    async with anyio.create_task_group() as tg:
        for name in ("w1", "w2", "w3"):
            tg.start_soon(wait, name)
            await anyio.sleep(0.01)  # fix the arrival order
        assert outcomes == {"w1": "busy"}  # w3 arrived with 2 already waiting
        gate.release()  # holder done: w2 then w3 run in order
    assert outcomes == {"w1": "busy", "w2": "ran", "w3": "ran"}
    assert gate.waiting == 0
    await gate.acquire()  # gate is free again
    gate.release()


async def test_a_cancelled_waiter_does_not_leak_the_gate() -> None:
    gate = SingleFlightGate(max_waiting=5)
    await gate.acquire()
    with anyio.move_on_after(0.02):
        await gate.acquire()
    assert gate.waiting == 0
    gate.release()
    await gate.acquire()  # not stuck busy
    gate.release()

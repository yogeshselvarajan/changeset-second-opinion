"""Single-flight async client for `strands-decider serve`.

One request at a time (the server shares a prefix cache and one GPU), a bounded wait queue where
the oldest waiter is rejected when it is full, one retry on connection errors, never on 422 or on
timeouts. Failures are typed; no failure ever produces a default answer.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

import anyio
import httpx

from cso.adapters.decider.aggregate import assemble_outputs
from cso.adapters.decider.errors import (
    DeciderBusy,
    DeciderSchemaError,
    DeciderStateTooLong,
    DeciderTimeout,
    DeciderUnavailable,
)
from cso.adapters.decider.panel import assemble_panel, build_fact_panel_plan
from cso.adapters.decider.questions import RequestPlan, build_plan
from cso.adapters.decider.validate import validate_response
from cso.domain.config import CommunityConfig
from cso.domain.models import DecisionOutputs
from cso.domain.panel import FactPanel
from cso.domain.receipt import DeciderIdentity
from cso.settings import Settings

GPU_TIMEOUT_S = 45.0
CPU_TIMEOUT_S = 90.0
MAX_WAITING = 20
_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError)


@dataclass(frozen=True)
class DeciderResult:
    """A validated, aggregated decision plus what is needed to build the receipt."""

    outputs: DecisionOutputs
    identity: DeciderIdentity
    questions_hash: str
    input_tokens: int
    output_tokens: int
    server_latency_ms: float | None
    latency_ms: int


@dataclass(frozen=True)
class PanelResult:
    """A validated fact panel plus what is needed to build the receipt."""

    panel: FactPanel
    identity: DeciderIdentity
    questions_hash: str
    input_tokens: int
    output_tokens: int
    server_latency_ms: float | None
    latency_ms: int


class _Waiter:
    def __init__(self) -> None:
        self.event = anyio.Event()
        self.rejected = False


class SingleFlightGate:
    """FIFO gate: one holder, at most `max_waiting` waiters, oldest rejected on overflow."""

    def __init__(self, max_waiting: int = MAX_WAITING) -> None:
        self._max_waiting = max_waiting
        self._busy = False
        self._waiters: deque[_Waiter] = deque()

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    async def acquire(self) -> None:
        if not self._busy and not self._waiters:
            self._busy = True
            return
        if len(self._waiters) >= self._max_waiting:
            oldest = self._waiters.popleft()
            oldest.rejected = True
            oldest.event.set()
        waiter = _Waiter()
        self._waiters.append(waiter)
        try:
            await waiter.event.wait()
        except BaseException:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            elif not waiter.rejected:
                self.release()  # ownership was handed to us just as we were cancelled
            raise
        if waiter.rejected:
            raise DeciderBusy("decider queue is full; the oldest waiting request was dropped")

    def release(self) -> None:
        if self._waiters:
            self._waiters.popleft().event.set()  # hand ownership over; stays busy
        else:
            self._busy = False


class DeciderClient:
    """Async client; share one instance per process so the gate serialises all callers."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = GPU_TIMEOUT_S,
        max_waiting: int = MAX_WAITING,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout_s, connect=3.0)
        )
        self.gate = SingleFlightGate(max_waiting)

    @classmethod
    def from_settings(
        cls, settings: Settings, *, device_class: Literal["gpu", "cpu"] | None = None
    ) -> DeciderClient:
        """Build from `CSO_DECIDER_URL`; 45 s timeout for GPU hosts, 90 s for CPU.

        `device_class` defaults to `CSO_DECIDER_DEVICE_CLASS`.
        """
        if not settings.decider_url:
            raise ValueError("CSO_DECIDER_URL is not set")
        timeout = (
            GPU_TIMEOUT_S
            if (device_class or settings.decider_device_class) == "gpu"
            else CPU_TIMEOUT_S
        )
        return cls(settings.decider_url, timeout_s=timeout)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def health(self) -> DeciderIdentity:
        """Identity of the running model (`GET /health`), serialised with other requests."""
        await self.gate.acquire()
        try:
            return await self._health()
        finally:
            self.gate.release()

    async def decide(self, state: str, config: CommunityConfig) -> DeciderResult:
        """Ask all eight questions in one request and return the validated, aggregated result."""
        started = time.perf_counter()
        plan = build_plan(state, config)
        identity, raw = await self._ask(plan)
        validated = validate_response(raw, plan)
        outputs = assemble_outputs(
            plan,
            validated,
            {
                "nature": [o.code for o in config.option_sets.nature],
                "response": [o.code for o in config.option_sets.response],
            },
        )
        return DeciderResult(
            outputs=outputs,
            identity=identity,
            questions_hash=plan.questions_hash,
            input_tokens=validated.input_tokens,
            output_tokens=validated.output_tokens,
            server_latency_ms=validated.server_latency_ms,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    async def decide_panel(self, state: str, config: CommunityConfig) -> PanelResult:
        """Ask the fact panel (ten yes/no probes, nature once) and return tri-state readings."""
        started = time.perf_counter()
        plan = build_fact_panel_plan(state, config)
        identity, raw = await self._ask(plan)
        validated = validate_response(raw, plan)
        return PanelResult(
            panel=assemble_panel(plan, validated, config),
            identity=identity,
            questions_hash=plan.questions_hash,
            input_tokens=validated.input_tokens,
            output_tokens=validated.output_tokens,
            server_latency_ms=validated.server_latency_ms,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    async def _ask(self, plan: RequestPlan) -> tuple[DeciderIdentity, Any]:
        """Serialised health check plus one `/v1/systemone` request; returns the raw response."""
        await self.gate.acquire()
        try:
            identity = await self._health()
            raw = await self._request("POST", "/v1/systemone", plan.request)
        finally:
            self.gate.release()
        return identity, raw

    async def _health(self) -> DeciderIdentity:
        raw = await self._request("GET", "/health", None)
        if not isinstance(raw, dict):
            raise DeciderSchemaError("health is not an object", raw)
        try:
            return DeciderIdentity(
                model=raw["model"],
                checkpoint=raw["checkpoint"],
                device=raw["device"],
                max_length=raw["max_length"],
                temperature=raw.get("temperature"),
                base_model=raw.get("base_model"),
                prefix_cache=raw.get("prefix_cache"),
            )
        except (KeyError, ValueError) as exc:
            raise DeciderSchemaError(f"health is malformed: {exc}", raw) from exc

    async def _request(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        for attempt in (1, 2):
            try:
                response = await self._http.request(method, path, json=body)
            except _RETRYABLE as exc:
                if attempt == 2:
                    raise DeciderUnavailable(f"connection failed: {exc!r}") from exc
                continue
            except httpx.TimeoutException as exc:
                raise DeciderTimeout(f"timeout: {exc!r}") from exc
            except httpx.HTTPError as exc:
                raise DeciderUnavailable(f"transport error: {exc!r}") from exc
            if response.status_code == 422:
                raise DeciderStateTooLong(response.text[:500])
            if response.status_code != 200:
                raise DeciderUnavailable(f"HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise DeciderSchemaError("response is not JSON", response.text[:500]) from exc
        raise AssertionError("unreachable")

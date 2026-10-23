"""One call from evidence text to a validated, aggregated, receipted decision."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from .aggregate import Aggregate, aggregate
from .client import AsyncDeciderClient, DeciderClient
from .questions import ChoiceSpec, NoulSpec, RequestPlan, build_request
from .receipt import Receipt, build_receipt
from .validate import ValidatedResponse, validate_response


@dataclass(frozen=True)
class GateResult:
    """Everything a caller needs: aggregates per question, nouls, and the receipt."""

    aggregates: dict[str, Aggregate]
    nouls: dict[str, float]
    validated: ValidatedResponse
    receipt: Receipt


def _finish(
    plan: RequestPlan,
    raw: object,
    choices: Sequence[ChoiceSpec],
    identity: dict[str, object],
    started: float,
) -> GateResult:
    validated = validate_response(raw, plan)
    aggregates = {
        spec.name: aggregate(
            [validated.choices[n].probabilities for n in plan.groups[spec.name]],
            list(spec.criteria),
        )
        for spec in choices
    }
    total = round((time.perf_counter() - started) * 1000)
    receipt = build_receipt(
        plan, validated, aggregates, decider=identity, timing_ms={"decider": total}
    )
    return GateResult(aggregates, validated.nouls, validated, receipt)


def decide(
    client: DeciderClient,
    state: str,
    choices: Sequence[ChoiceSpec],
    nouls: Sequence[NoulSpec] = (),
    *,
    permutations: int = 3,
) -> GateResult:
    """Ask every question in one request and return the gated result (sync)."""
    started = time.perf_counter()
    plan = build_request(state, choices, nouls, permutations=permutations)
    identity = client.health()
    raw = client.systemone(plan.request)
    return _finish(plan, raw, choices, identity, started)


async def adecide(
    client: AsyncDeciderClient,
    state: str,
    choices: Sequence[ChoiceSpec],
    nouls: Sequence[NoulSpec] = (),
    *,
    permutations: int = 3,
) -> GateResult:
    """Ask every question in one request and return the gated result (async)."""
    started = time.perf_counter()
    plan = build_request(state, choices, nouls, permutations=permutations)
    identity = await client.health()
    raw = await client.systemone(plan.request)
    return _finish(plan, raw, choices, identity, started)

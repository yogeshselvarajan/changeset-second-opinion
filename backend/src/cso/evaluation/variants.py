"""Ask the fact panel with different probe wording (ablations) through the real Decider client.

The request is the product's own plan with only the probe instruction strings replaced, so
the evidence text, the nature question, the option sets and the strict response validation are
identical. Question text for the shipped product stays a constant in `cso.domain.panel`.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Awaitable, Callable, Mapping

from cso.adapters.decider import (
    DeciderClient,
    PanelResult,
    RequestPlan,
    assemble_panel,
    build_fact_panel_plan,
    validate_response,
)
from cso.adapters.decider.questions import _hash
from cso.domain.config import CommunityConfig

PanelDecide = Callable[[str, CommunityConfig], Awaitable[PanelResult]]


def variant_plan(
    state: str, config: CommunityConfig, instructions: Mapping[str, str]
) -> RequestPlan:
    """The product panel plan for `state` with the probe instructions replaced.

    `instructions` must cover exactly the probes the plan asks; anything else is refused so a
    variant can neither drop a question nor add one.
    """
    plan = build_fact_panel_plan(state, config)
    if set(instructions) != set(plan.nouls):
        raise ValueError("a variant must give an instruction for every panel probe and no others")
    questions = copy.deepcopy(plan.request["questions"])
    for noul_id in plan.nouls:
        questions[noul_id]["instructions"] = instructions[noul_id]
    return RequestPlan(
        request={"state": state, "questions": questions},
        orders=plan.orders,
        groups=plan.groups,
        nouls=plan.nouls,
        questions_hash=_hash(questions),
    )


def make_variant_decide(client: DeciderClient, instructions: Mapping[str, str]) -> PanelDecide:
    """A `decide(state, config)` coroutine that asks the panel with `instructions`."""

    async def decide(state: str, config: CommunityConfig) -> PanelResult:
        started = time.perf_counter()
        plan = variant_plan(state, config, instructions)
        identity, raw = await client._ask(plan)
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

    return decide

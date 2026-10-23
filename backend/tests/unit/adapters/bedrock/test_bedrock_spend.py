from __future__ import annotations

import pytest
from bedrock_support import TONE, fixture_evidence

from cso.adapters.bedrock import (
    GOOD_INPUT,
    BudgetExceeded,
    DraftRequest,
    FakeDrafter,
    MeteredDrafter,
    produce_draft,
)
from cso.domain.enums import DraftStatus, Response

MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


class FakeGate:
    """A spend gate that allows a set number of calls and records what it was asked to count."""

    def __init__(self, allowed_calls: int | None = None, usd_per_call: float = 0.01) -> None:
        self.allowed_calls = allowed_calls
        self.usd_per_call = usd_per_call
        self.allow_asked = 0
        self.recorded: list[tuple[str, int, int]] = []

    def allow(self) -> bool:
        self.allow_asked += 1
        return self.allowed_calls is None or len(self.recorded) < self.allowed_calls

    def record(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        self.recorded.append((model_id, input_tokens, output_tokens))
        return self.usd_per_call


def request() -> DraftRequest:
    return DraftRequest(
        evidence_text="E1 way/1 modify", response_type=Response.ASK_SOURCE_QUESTION, tone=TONE
    )


async def test_a_call_is_checked_first_then_recorded_with_its_model_and_tokens() -> None:
    gate, inner = FakeGate(), FakeDrafter(model_id=MODEL)
    metered = MeteredDrafter(inner, gate)
    raw = await metered.draft(request())
    assert raw.input_tokens == 900 and metered.model_id == MODEL
    assert gate.allow_asked == 1 and gate.recorded == [(MODEL, 900, 120)]
    assert metered.calls == 1 and metered.usd == pytest.approx(0.01)


async def test_the_dollars_of_several_calls_add_up() -> None:
    metered = MeteredDrafter(FakeDrafter(), FakeGate(usd_per_call=0.004))
    await metered.draft(request())
    await metered.draft(request())
    assert metered.calls == 2 and metered.usd == pytest.approx(0.008)


async def test_at_the_ceiling_the_inner_drafter_is_never_called() -> None:
    gate, inner = FakeGate(allowed_calls=0), FakeDrafter()
    metered = MeteredDrafter(inner, gate)
    with pytest.raises(BudgetExceeded) as caught:
        await metered.draft(request())
    assert caught.value.code == "budget_exceeded"
    assert inner.calls == 0 and gate.recorded == [] and metered.usd == 0.0


async def test_a_denied_call_becomes_a_template_with_the_budget_reason_and_no_model_call() -> None:
    inner = FakeDrafter()
    outcome = await produce_draft(
        response_type=Response.ASK_SOURCE_QUESTION,
        evidence=await fixture_evidence("05"),
        tone=TONE,
        language="en",
        drafter=MeteredDrafter(inner, FakeGate(allowed_calls=0)),
    )
    assert outcome.status is DraftStatus.TEMPLATE_FALLBACK and outcome.model_id is None
    assert outcome.usage["fallback_reason"] == "budget_exceeded"
    assert outcome.usage["model_calls"] == 0 and inner.calls == 0


async def test_the_ceiling_can_be_reached_between_the_first_draft_and_its_regeneration() -> None:
    bad = {**GOOD_INPUT, "body": "I looked at E1 and we must stop this now."}  # banned words
    inner, gate = FakeDrafter(bad), FakeGate(allowed_calls=1, usd_per_call=0.02)
    metered = MeteredDrafter(inner, gate)
    outcome = await produce_draft(
        response_type=Response.ASK_SOURCE_QUESTION,
        evidence=await fixture_evidence("05"),
        tone=TONE,
        language="en",
        drafter=metered,
    )
    assert outcome.status is DraftStatus.TEMPLATE_FALLBACK
    assert outcome.usage["fallback_reason"] == "budget_exceeded"
    assert outcome.usage["model_calls"] == 1 and inner.calls == 1
    assert metered.usd == pytest.approx(0.02)  # only the call that was made is metered

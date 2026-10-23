"""Helpers for the drafting-agent tests: stored runs, contexts and recording models."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from strands.models import Model

from cso.adapters.bedrock import DraftBudget, Drafter
from cso.adapters.osm import ReplayClient, collect
from cso.agent import DraftContext, ScriptedToolModel
from cso.domain.config import CommunityConfig
from cso.domain.enums import Lane, Response, RunStatus, Severity
from cso.domain.evidence import RenderedEvidence, render
from cso.domain.models import AnalysisResult, RuleHit

CONFIG = CommunityConfig.load()
TONE = CONFIG.tone
CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"
ALL_RESPONSES = list(Response)


def run_result(
    response: Response | None,
    *,
    status: RunStatus = RunStatus.SUCCEEDED,
    limited_to: Response | None = None,
) -> AnalysisResult:
    """A stored run as the gate sees it; `limited_to` adds an R3 hit (drafting limited)."""
    rules = []
    if limited_to is not None:
        rules.append(
            RuleHit(
                code="R3",
                label="Evidence is thin",
                severity=Severity.WARN,
                triggered_by={"drafting_limited_to": limited_to.value},
            )
        )
    return AnalysisResult(
        id=uuid4(),
        snapshot_id=uuid4(),
        config_version="test-config",
        status=status,
        lane=Lane.REVIEW_SUGGESTED if status is RunStatus.SUCCEEDED else Lane.RULES_ONLY,
        response=response,
        rules_fired=rules,
    )


async def fixture_evidence(prefix: str) -> RenderedEvidence:
    case_dir = next(p for p in sorted(CASES.iterdir()) if p.name.startswith(prefix))
    client = ReplayClient(case_dir)
    snapshot = await collect(client, client.case.changeset.id)
    return render(snapshot, CONFIG, profile="compact")


def make_ctx(
    run: AnalysisResult,
    evidence: RenderedEvidence,
    drafter: Drafter | None = None,
    budget: DraftBudget | None = None,
) -> DraftContext:
    return DraftContext(
        run=run, evidence=evidence, tone=TONE, language="en", drafter=drafter, budget=budget
    )


class RecordingModel(ScriptedToolModel):
    """The scripted model that also records exactly what the agent sends to a model."""

    def __init__(self, response_type: str) -> None:
        super().__init__(response_type)
        self.system_prompts: list[str | None] = []
        self.messages: list[Any] = []

    async def stream(  # type: ignore[override]
        self, messages: Any, tool_specs: Any = None, system_prompt: str | None = None, **kw: Any
    ) -> AsyncIterable[dict[str, Any]]:
        self.system_prompts.append(system_prompt)
        self.messages.append(json.loads(json.dumps(messages, default=str)))
        async for event in super().stream(messages, tool_specs, system_prompt, **kw):
            yield event


class OtherToolModel(Model):
    """Asks for a tool the agent does not have (turn 1), then ends."""

    def __init__(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        self._name, self._input, self._turn = tool_name, tool_input, 0

    def update_config(self, **model_config: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {}

    async def structured_output(  # type: ignore[override]
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError
        yield {}  # pragma: no cover

    async def stream(  # type: ignore[override]
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterable[dict[str, Any]]:
        self._turn += 1
        yield {"messageStart": {"role": "assistant"}}
        if self._turn == 1:
            yield {
                "contentBlockStart": {"start": {"toolUse": {"toolUseId": "x1", "name": self._name}}}
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self._input)}}}}
            yield {"contentBlockStop": {}}
            stop = "tool_use"
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "done"}}}
            yield {"contentBlockStop": {}}
            stop = "end_turn"
        yield {"messageStop": {"stopReason": stop}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }

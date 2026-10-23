"""The drafting agent: a Strands Agent with ONE tool, gated by the stored decision.

`DeciderGate` is the enforcement point. It runs before every tool call, reads the response types
the STORED, reconciled run allows (`allowed_comment_types`), and cancels the call for anything
else, so a forbidden draft never reaches the drafter or Bedrock. The agent prompt holds only the
response type and a fixed tone line; the tool reads the evidence from the context, never from the
model.

Fail closed: no stored decision, a failed run, or any other tool name means nothing is drafted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models import Model

from cso.adapters.bedrock import (
    DraftBudget,
    Drafter,
    DraftOutcome,
    produce_draft,
)
from cso.agent.constants import TOOL_NAME
from cso.agent.scripted import ScriptedToolModel
from cso.domain.config import Tone
from cso.domain.enums import Response
from cso.domain.evidence import RenderedEvidence
from cso.domain.lanes import allowed_comment_types
from cso.domain.models import AnalysisResult, Draft
from cso.settings import Settings

AGENT_SYSTEM = (
    "You assist a human validator. Call the draft_comment tool exactly once, using the response "
    "type you are given, then reply with one short sentence. Never write comment text yourself and "
    "never ask for evidence: the tool reads it. Tone: warm, plain and factual."
)
_SAFE_NAME = re.compile(r"[^a-z_]")


class DraftNotAllowed(Exception):
    """The stored decision does not allow this draft; nothing was drafted."""

    code = "draft_not_allowed"


class DraftNotProduced(Exception):
    """The agent finished without calling the tool (and the gate did not block it)."""

    code = "draft_not_produced"


@dataclass
class DraftContext:
    """Everything one drafting run needs. `run` is the stored decision the gate enforces."""

    run: AnalysisResult
    evidence: RenderedEvidence
    tone: Tone
    language: str
    drafter: Drafter | None
    budget: DraftBudget | None = None
    outcome: DraftOutcome | None = None  # set by the tool
    blocked: str | None = None  # set by the gate
    tool_calls: int = 0


class DeciderGate(HookProvider):
    """Cancels `draft_comment` unless the stored decision allows the requested response type."""

    def __init__(self, ctx: DraftContext) -> None:
        self._ctx = ctx

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check)

    def check(self, event: BeforeToolCallEvent) -> None:
        ctx = self._ctx
        name = str(event.tool_use.get("name", ""))
        if name != TOOL_NAME:
            ctx.blocked = "unknown_tool"
            event.cancel_tool = "Only the draft_comment tool is available."
            return
        raw = event.tool_use.get("input")
        requested = str(raw.get("response_type", "")) if isinstance(raw, dict) else ""
        requested = _SAFE_NAME.sub("", requested.lower())[:40]
        allowed = {r.value for r in allowed_comment_types(ctx.run)}
        if requested not in allowed:
            ctx.blocked = "response_type_not_allowed"
            event.cancel_tool = f"The stored decision does not allow a '{requested}' comment."
            return
        if ctx.outcome is not None:
            ctx.blocked = "already_drafted"
            event.cancel_tool = "A draft was already produced for this decision."


def build_draft_tool(ctx: DraftContext) -> Any:
    """The single tool; it drafts from the context's evidence and records the outcome there."""

    @tool
    async def draft_comment(response_type: str) -> dict[str, Any]:
        """Draft a changeset comment of the given response type from the stored evidence."""
        ctx.tool_calls += 1
        try:
            requested = Response(response_type)
        except ValueError:
            return {"status": "error", "content": [{"text": "Unknown response type."}]}
        ctx.outcome = await produce_draft(
            response_type=requested,
            evidence=ctx.evidence,
            tone=ctx.tone,
            language=ctx.language,
            drafter=ctx.drafter,
            budget=ctx.budget,
        )
        return {
            "status": "success",
            "content": [{"text": f"Draft stored with status {ctx.outcome.status.value}."}],
        }

    return draft_comment


def build_agent_model(settings: Settings, response_type: Response) -> Model:
    """The agent's model: always the offline scripted one, in every mode.

    The agent's only job is to call the one `draft_comment` tool for the response type the stored
    decision allows; a language model adds nothing to that. A Bedrock-backed agent model would make
    Converse calls that bypass the daily dollar ceiling and the spend metering (review F-M1), so the
    only Bedrock calls left are the inner drafter's, which go through `MeteredDrafter` and the
    `SpendGate`. `settings` is kept so callers need not change.
    """
    del settings
    return ScriptedToolModel(response_type.value)


async def run_draft(ctx: DraftContext, model: Model, response_type: Response) -> Draft:
    """Run the agent once and return the draft it produced.

    Raises DraftNotAllowed when the gate blocked the call and DraftNotProduced when the agent ended
    without drafting. The returned draft is a candidate only; nothing is posted anywhere.
    """
    agent = Agent(
        model=model,
        tools=[build_draft_tool(ctx)],
        hooks=[DeciderGate(ctx)],
        system_prompt=AGENT_SYSTEM,
        callback_handler=None,
    )
    await agent.invoke_async(f"Draft a {response_type.value} comment.")
    if ctx.outcome is None:
        if ctx.blocked is not None:
            raise DraftNotAllowed(ctx.blocked)
        raise DraftNotProduced("the agent did not call the draft tool")
    outcome = ctx.outcome
    return Draft(
        run_id=ctx.run.id,
        response_type=response_type,
        status=outcome.status,
        model_id=outcome.model_id,
        greeting=outcome.fields.greeting,
        body=outcome.fields.body,
        closing=outcome.fields.closing,
        cited_evidence_ids=list(outcome.fields.cited_evidence_ids),
        validation=outcome.validation,
        config_version=ctx.run.config_version,
    )

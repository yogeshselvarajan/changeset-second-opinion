"""A Strands model that always asks for the `draft_comment` tool, with no network and no cost.

Used in replay mode and whenever a real Bedrock call is not enabled, so the real Strands Agent, the
real `DeciderGate` hook and the real tool all run exactly as they do in production, driven by a
fixed policy ("call the tool once for the reconciled response type") instead of a language model.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from strands.models import Model

from cso.agent.constants import TOOL_NAME


class ScriptedToolModel(Model):
    """Turn 1 requests the tool for `response_type`; turn 2 ends the conversation."""

    def __init__(self, response_type: str) -> None:
        self._response_type = response_type
        self._turn = 0
        self._config: dict[str, Any] = {}

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self._config)

    async def structured_output(  # type: ignore[override]
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("the scripted model has no structured output")
        yield {}  # pragma: no cover

    async def stream(  # type: ignore[override]
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterable[dict[str, Any]]:
        self._turn += 1
        yield {"messageStart": {"role": "assistant"}}
        if self._turn == 1:
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": "scripted-1", "name": TOOL_NAME}}
                }
            }
            payload = json.dumps({"response_type": self._response_type})
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": payload}}}}
            yield {"contentBlockStop": {}}
            stop_reason = "tool_use"
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "The draft is ready for review."}}}
            yield {"contentBlockStop": {}}
            stop_reason = "end_turn"
        yield {"messageStop": {"stopReason": stop_reason}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }

"""Deterministic stand-ins for Bedrock, for tests and replay mode. They never touch the network.

`FakeBedrockRuntime` has the one `converse` method the real client uses, so the real
`BedrockDrafter` (request building, retries, parsing) runs against it unchanged.
`FakeDrafter` skips that layer.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from typing import Any

from cso.adapters.bedrock.client import TOOL_NAME
from cso.adapters.bedrock.types import DraftRequest, RawDraft

GOOD_INPUT: dict[str, Any] = {
    "greeting": "Hello, and thank you for your edit.",
    "body": (
        "I noticed the changeset and had a look at the tags in E1. Could you tell me where the "
        "information came from, for example a survey or imagery? It helps other mappers follow."
    ),
    "closing": "Thanks for your help!",
    "cited_evidence_ids": ["E1"],
}


class FakeClientError(Exception):
    """Shaped like botocore's ClientError: carries `response['Error']['Code']`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


def tool_use_reply(
    data: dict[str, Any] | None = None, *, stop_reason: str = "tool_use"
) -> dict[str, Any]:
    """A Converse reply that calls `draft_comment` with `data` (default: a clean draft)."""
    return {
        "stopReason": stop_reason,
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": TOOL_NAME,
                            "input": dict(GOOD_INPUT if data is None else data),
                        }
                    }
                ],
            }
        },
        "usage": {"inputTokens": 900, "outputTokens": 120, "totalTokens": 1020},
    }


class FakeBedrockRuntime:
    """Plays a script of replies and errors in order, then repeats the last step.

    A step is a reply dict, an exception to raise, or a callable taking the request kwargs.
    Every call is recorded in `calls` so tests can assert what was (not) sent.
    """

    def __init__(self, *steps: dict[str, Any] | BaseException | Callable[..., Any]) -> None:
        self._steps: deque[Any] = deque(steps or (tool_use_reply(),))
        self._last: Any = self._steps[-1]
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        step = self._steps.popleft() if self._steps else self._last
        self._last = step
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            result: dict[str, Any] = step(**kwargs)
            return result
        return dict(step)

    def user_payloads(self) -> list[dict[str, Any]]:
        """The decoded JSON user message of every call."""
        payloads: list[dict[str, Any]] = []
        for call in self.calls:
            text = call["messages"][0]["content"][0]["text"]
            payloads.append(json.loads(text))
        return payloads


class FakeDrafter:
    """A drafter that returns a fixed draft (or raises), counting how often it was asked."""

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
        model_id: str = "fake-model",
    ) -> None:
        self.model_id = model_id
        self._data = dict(GOOD_INPUT if data is None else data)
        self._error = error
        self.requests: list[DraftRequest] = []

    @property
    def calls(self) -> int:
        """How many drafts were requested."""
        return len(self.requests)

    async def draft(self, request: DraftRequest) -> RawDraft:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return RawDraft(
            greeting=str(self._data["greeting"]),
            body=str(self._data["body"]),
            closing=str(self._data["closing"]),
            cited_evidence_ids=tuple(self._data["cited_evidence_ids"]),
            model_id=self.model_id,
            input_tokens=900,
            output_tokens=120,
        )

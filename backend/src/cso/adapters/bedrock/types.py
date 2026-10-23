"""Shared types for drafting: the request, the raw draft, the drafter protocol and its errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cso.domain.config import Tone
from cso.domain.enums import Response


@dataclass(frozen=True)
class DraftRequest:
    """Everything a drafter may see: the evidence block and application-chosen settings.

    Nothing else is passed: no case id, no run data, no reviewer text. `violations` is only set on
    the one regeneration and holds fixed phrases, never text from the first attempt.
    """

    evidence_text: str
    response_type: Response
    tone: Tone
    language: str = "en"
    violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawDraft:
    """What the model returned through the `draft_comment` tool, before validation."""

    greeting: str
    body: str
    closing: str
    cited_evidence_ids: tuple[str, ...]
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "tool_use"
    extras: dict[str, str] = field(default_factory=dict)


class Drafter(Protocol):
    """Anything that can draft: the Bedrock client, or a fake in tests and replay."""

    model_id: str

    async def draft(self, request: DraftRequest) -> RawDraft:
        """Return a raw draft, or raise a `DraftingError`."""
        ...


class DraftingError(Exception):
    """The model path failed. The caller falls back to a template; `code` says why."""

    code = "drafting_error"


class BedrockUnavailable(DraftingError):
    """Throttling, service or model-not-ready errors persisted through every retry."""

    code = "bedrock_unavailable"


class BedrockTimeout(DraftingError):
    """The call exceeded its time limit (after one retry for a model timeout)."""

    code = "bedrock_timeout"


class BedrockRefused(DraftingError):
    """A non-retryable service error such as missing access or a validation error."""

    code = "bedrock_refused"


class BedrockOutputError(DraftingError):
    """The reply was not a usable `draft_comment` tool call (wrong stop reason or shape)."""

    code = "bedrock_output"

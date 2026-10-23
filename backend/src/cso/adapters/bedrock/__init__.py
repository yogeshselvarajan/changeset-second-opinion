"""Drafting through Amazon Bedrock (Claude Haiku 4.5), with an offline template path.

Nothing here posts anything: a draft is a candidate that a person edits and posts under their own
identity. A real Bedrock call needs live mode AND `CSO_LIVE_BEDROCK=1`.
"""

from cso.adapters.bedrock.budget import DraftBudget
from cso.adapters.bedrock.client import (
    DRAFT_TOOL,
    LIVE_FLAG_ENV,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    BedrockDrafter,
    build_converse_request,
    build_drafter,
    build_user_payload,
    live_bedrock_enabled,
    parse_converse_response,
)
from cso.adapters.bedrock.drafting import DraftOutcome, produce_draft, template_outcome
from cso.adapters.bedrock.fake import (
    GOOD_INPUT,
    FakeBedrockRuntime,
    FakeClientError,
    FakeDrafter,
    tool_use_reply,
)
from cso.adapters.bedrock.pricing import (
    PRICING_DISCLAIMER,
    Rates,
    estimate_usd,
    rates_for,
)
from cso.adapters.bedrock.spend import BudgetExceeded, MeteredDrafter, SpendGate
from cso.adapters.bedrock.types import (
    BedrockOutputError,
    BedrockRefused,
    BedrockTimeout,
    BedrockUnavailable,
    Drafter,
    DraftingError,
    DraftRequest,
    RawDraft,
)

__all__ = [
    "DRAFT_TOOL",
    "GOOD_INPUT",
    "LIVE_FLAG_ENV",
    "PRICING_DISCLAIMER",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "BedrockDrafter",
    "BedrockOutputError",
    "BedrockRefused",
    "BedrockTimeout",
    "BedrockUnavailable",
    "BudgetExceeded",
    "DraftBudget",
    "DraftOutcome",
    "DraftRequest",
    "Drafter",
    "DraftingError",
    "FakeBedrockRuntime",
    "FakeClientError",
    "FakeDrafter",
    "MeteredDrafter",
    "Rates",
    "RawDraft",
    "SpendGate",
    "build_converse_request",
    "build_drafter",
    "build_user_payload",
    "estimate_usd",
    "live_bedrock_enabled",
    "parse_converse_response",
    "produce_draft",
    "rates_for",
    "template_outcome",
    "tool_use_reply",
]

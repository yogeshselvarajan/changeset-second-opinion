from __future__ import annotations

import json
import time
from typing import Any

import pytest
from bedrock_support import TONE, Sleeps

from cso.adapters.bedrock import (
    DRAFT_TOOL,
    GOOD_INPUT,
    SYSTEM_PROMPT,
    BedrockDrafter,
    BedrockOutputError,
    BedrockRefused,
    BedrockTimeout,
    BedrockUnavailable,
    DraftRequest,
    FakeBedrockRuntime,
    FakeClientError,
    build_converse_request,
    build_user_payload,
    parse_converse_response,
    tool_use_reply,
)
from cso.adapters.bedrock.client import PAYLOAD_KEYS, TOOL_NAME
from cso.domain.enums import Response

MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def request(**overrides: Any) -> DraftRequest:
    base: dict[str, Any] = {
        "evidence_text": 'E1 way/1 modify tags: "a"="b" → "a"="c"',
        "response_type": Response.ASK_SOURCE_QUESTION,
        "tone": TONE,
        "language": "en",
    }
    base.update(overrides)
    return DraftRequest(**base)


def drafter(client: FakeBedrockRuntime, sleeps: Sleeps | None = None) -> BedrockDrafter:
    return BedrockDrafter(
        client, model_id=MODEL, sleep=sleeps or Sleeps(), rng=lambda: 0.5, timeout_s=5.0
    )


# ----------------------------------------------------------------------------- request shape


def test_the_request_forces_the_draft_tool_and_uses_the_constant_system_prompt() -> None:
    args = build_converse_request(MODEL, request())
    assert args["modelId"] == MODEL
    assert args["system"] == [{"text": SYSTEM_PROMPT}]
    assert args["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert args["toolConfig"]["tools"] == [DRAFT_TOOL]
    assert args["inferenceConfig"] == {"maxTokens": 400, "temperature": 0.3}
    assert len(args["messages"]) == 1 and args["messages"][0]["role"] == "user"


def test_the_tool_schema_matches_the_documented_fields() -> None:
    schema = DRAFT_TOOL["toolSpec"]["inputSchema"]["json"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"greeting", "body", "closing", "cited_evidence_ids"}
    assert schema["properties"]["body"]["maxLength"] == 700
    assert schema["properties"]["cited_evidence_ids"]["maxItems"] == 6


def test_the_user_payload_holds_only_the_evidence_block_type_tone_language_and_links() -> None:
    payload = json.loads(build_user_payload(request(language="fr")))
    assert set(payload) == {"evidence", "response_type", "tone", "language", "allowed_links"}
    assert payload["evidence"].startswith("<evidence>\n") and payload["evidence"].endswith(
        "\n</evidence>"
    )
    assert payload["response_type"] == "ask_source_question"
    assert payload["language"] == "fr"
    assert payload["allowed_links"] == TONE.allowed_links
    assert payload["tone"]["language_policy"] == TONE.language_policy


def test_only_the_regeneration_adds_a_fix_note_and_nothing_else() -> None:
    payload = json.loads(build_user_payload(request(violations=("Use plain text only.",))))
    assert payload["fix_these"] == "Use plain text only."
    assert set(payload) == set(PAYLOAD_KEYS)


async def test_a_whole_converse_call_never_carries_anything_outside_the_allowed_payload() -> None:
    fake = FakeBedrockRuntime()
    await drafter(fake).draft(request())
    assert len(fake.calls) == 1
    assert set(fake.user_payloads()[0]) <= PAYLOAD_KEYS
    assert set(fake.calls[0]) == {
        "modelId",
        "system",
        "messages",
        "inferenceConfig",
        "toolConfig",
    }


# ----------------------------------------------------------------------------- parsing


def test_a_tool_use_reply_becomes_a_raw_draft_with_usage() -> None:
    raw = parse_converse_response(tool_use_reply(), MODEL)
    assert raw.greeting == GOOD_INPUT["greeting"] and raw.cited_evidence_ids == ("E1",)
    assert (raw.input_tokens, raw.output_tokens, raw.model_id) == (900, 120, MODEL)


@pytest.mark.parametrize("stop", ["end_turn", "max_tokens", "content_filtered", ""])
def test_any_stop_reason_other_than_tool_use_is_an_output_error(stop: str) -> None:
    with pytest.raises(BedrockOutputError):
        parse_converse_response(tool_use_reply(stop_reason=stop), MODEL)


@pytest.mark.parametrize(
    "data",
    [
        {"greeting": "a", "body": "b", "closing": "c"},
        {"greeting": "a", "body": 5, "closing": "c", "cited_evidence_ids": []},
        {"greeting": "a", "body": "b", "closing": "c", "cited_evidence_ids": "E1"},
        {"greeting": "a", "body": "b", "closing": "c", "cited_evidence_ids": [1]},
    ],
)
def test_a_malformed_tool_input_is_an_output_error(data: dict[str, Any]) -> None:
    with pytest.raises(BedrockOutputError):
        parse_converse_response(tool_use_reply(data), MODEL)


def test_a_reply_without_the_tool_call_is_an_output_error() -> None:
    reply = {"stopReason": "tool_use", "output": {"message": {"content": [{"text": "hi"}]}}}
    with pytest.raises(BedrockOutputError):
        parse_converse_response(reply, MODEL)


# ----------------------------------------------------------------------------- retries


async def test_throttling_is_retried_with_jittered_backoff_then_succeeds() -> None:
    fake = FakeBedrockRuntime(
        FakeClientError("ThrottlingException"),
        FakeClientError("ServiceUnavailableException"),
        tool_use_reply(),
    )
    sleeps = Sleeps()
    raw = await drafter(fake, sleeps).draft(request())
    assert raw.body == GOOD_INPUT["body"]
    assert len(fake.calls) == 3
    assert sleeps.delays == pytest.approx([1.0, 2.0])  # rng 0.5 means no jitter


async def test_backoff_jitter_stays_within_twenty_percent() -> None:
    for rng_value, factor in ((0.0, 0.8), (1.0, 1.2)):
        fake = FakeBedrockRuntime(FakeClientError("ThrottlingException"), tool_use_reply())
        sleeps = Sleeps()
        client = BedrockDrafter(fake, model_id=MODEL, sleep=sleeps, rng=lambda v=rng_value: v)
        await client.draft(request())
        assert sleeps.delays == pytest.approx([1.0 * factor])


async def test_three_throttled_attempts_raise_unavailable() -> None:
    fake = FakeBedrockRuntime(FakeClientError("ThrottlingException"))
    d = drafter(fake)
    with pytest.raises(BedrockUnavailable):
        await d.draft(request())
    assert len(fake.calls) == 3 and d.attempts == 3


async def test_a_model_timeout_is_retried_once_then_succeeds() -> None:
    fake = FakeBedrockRuntime(FakeClientError("ModelTimeoutException"), tool_use_reply())
    assert (await drafter(fake).draft(request())).model_id == MODEL
    assert len(fake.calls) == 2


async def test_two_model_timeouts_raise_timeout() -> None:
    fake = FakeBedrockRuntime(FakeClientError("ModelTimeoutException"))
    with pytest.raises(BedrockTimeout):
        await drafter(fake).draft(request())
    assert len(fake.calls) == 2


async def test_a_call_that_exceeds_the_time_limit_is_cut_off_and_retried_once() -> None:
    def slow(**_: Any) -> dict[str, Any]:
        time.sleep(0.25)
        return tool_use_reply()

    fake = FakeBedrockRuntime(slow)
    d = BedrockDrafter(fake, model_id=MODEL, sleep=Sleeps(), timeout_s=0.05)
    with pytest.raises(BedrockTimeout):
        await d.draft(request())
    assert len(fake.calls) == 2


@pytest.mark.parametrize("code", ["AccessDeniedException", "ValidationException", "Other", ""])
async def test_other_errors_are_refused_without_retry(code: str) -> None:
    fake = FakeBedrockRuntime(FakeClientError(code) if code else RuntimeError("boom"))
    with pytest.raises(BedrockRefused):
        await drafter(fake).draft(request())
    assert len(fake.calls) == 1


async def test_a_wrong_stop_reason_is_not_retried() -> None:
    fake = FakeBedrockRuntime(tool_use_reply(stop_reason="end_turn"))
    with pytest.raises(BedrockOutputError):
        await drafter(fake).draft(request())
    assert len(fake.calls) == 1

"""Redaction: secrets are masked, user names hashed, evidence truncated, facts left alone."""

from __future__ import annotations

import secrets

import pytest

from cso.observability.redaction import (
    EVIDENCE_STRING,
    MAX_STRING,
    REDACTED,
    hash_name,
    redact_event,
    scrub_text,
)

INVITE = "cso-0a1b2c3d-" + secrets.token_urlsafe(24)
SESSION = secrets.token_urlsafe(32)  # 43 url-safe characters, the shape of a session token
CSRF = secrets.token_urlsafe(32)


def redact(**event: object) -> dict[str, object]:
    return redact_event(None, "info", dict(event))


@pytest.mark.parametrize(
    "key",
    [
        "session",
        "session_id",
        "csrf",
        "x-csrf",
        "invite_code",
        "invite",
        "authorization",
        "Authorization",
        "cookie",
        "set-cookie",
        "password",
        "api_key",
        "x-api-key",
        "aws_secret_access_key",
        "token",
        "access_token",
    ],
)
def test_values_under_secret_keys_are_replaced_whatever_they_look_like(key: str) -> None:
    assert redact(**{key: "anything at all"})[key] == REDACTED
    assert redact(**{key: {"nested": SESSION}})[key] == REDACTED


def test_counters_with_secret_sounding_names_are_kept() -> None:
    out = redact(input_tokens=1500, output_tokens=12, session_count=3, tokens=9)
    assert out == {"input_tokens": 1500, "output_tokens": 12, "session_count": 3, "tokens": 9}


def test_invite_codes_and_tokens_are_scrubbed_inside_free_text() -> None:
    text = f"login with {INVITE} then session {SESSION} and csrf {CSRF}"
    out = scrub_text(text)
    assert INVITE not in out and SESSION not in out and CSRF not in out
    assert "cso-<redacted>" in out and "<redacted-token>" in out


def test_cookie_headers_and_bearer_tokens_are_scrubbed() -> None:
    out = scrub_text(f"Cookie: cso_session={SESSION}; cso_csrf={CSRF} | Bearer abcdefghijklmnop12")
    assert SESSION not in out and CSRF not in out and "abcdefghijklmnop12" not in out
    assert "cso_session=<redacted>" in out


def test_aws_keys_and_key_value_secrets_are_scrubbed() -> None:
    out = scrub_text("key AKIAABCDEFGHIJKLMNOP and password=hunter2 and api_key: s3cr3t")
    assert "AKIAABCDEFGHIJKLMNOP" not in out
    assert "hunter2" not in out and "s3cr3t" not in out


def test_scrubbing_reaches_nested_structures_and_exception_text() -> None:
    out = redact(
        event="failed",
        detail={"errors": [f"bad code {INVITE}", {"hint": f"cookie cso_session={SESSION}"}]},
        exception=f"Traceback ... ValueError: {INVITE}",
    )
    assert INVITE not in str(out) and SESSION not in str(out)


def test_user_names_are_hashed_stably_and_never_logged_raw() -> None:
    first = redact(user="Alice Mapper", display_name="Alice Mapper")
    second = redact(username="Alice Mapper")
    assert "Alice" not in str(first) and "Alice" not in str(second)
    assert first["user"] == first["display_name"] == second["username"] == hash_name("Alice Mapper")
    assert hash_name("Alice Mapper") != hash_name("Bob Mapper")


def test_system_actors_are_not_treated_as_personal_data() -> None:
    assert redact(actor="system")["actor"] == "system"
    assert redact(actor="anonymous")["actor"] == "anonymous"


def test_evidence_like_text_is_truncated_tightly_and_other_text_loosely() -> None:
    long_text = "x" * 1000
    out = redact(rendered_text=long_text, comment=long_text, note=long_text)
    assert str(out["rendered_text"]).startswith("x" * EVIDENCE_STRING)
    assert len(str(out["rendered_text"])) < EVIDENCE_STRING + 30
    assert "[+920 chars]" in str(out["rendered_text"])
    assert len(str(out["note"])) < MAX_STRING + 30


def test_ids_counts_and_short_text_pass_through_unchanged() -> None:
    event = {
        "event": "analysis.persisted",
        "request_id": "req-1",
        "job_id": "5d1c",
        "lane": "review_suggested",
        "duration_ms": 12.5,
        "changeset_id": 185609377,
        "evidence_version": "sha256:" + "ab" * 32,
    }
    assert redact_event(None, "info", dict(event)) == event


def test_redaction_returns_a_copy_and_leaves_the_input_untouched() -> None:
    event = {"session": SESSION, "user": "Alice"}
    out = redact_event(None, "info", event)
    assert event == {"session": SESSION, "user": "Alice"}
    assert out is not event

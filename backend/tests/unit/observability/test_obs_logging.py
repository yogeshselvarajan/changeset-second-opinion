"""The configured pipeline: JSON lines with ids, redaction before rendering, idempotent setup."""

from __future__ import annotations

import io
import secrets

import structlog

from cso.observability import current_context, log_context, reset_context
from cso.observability import logging as obs_logging
from cso.observability.logging import configure_logging, get_logger
from cso.settings import Settings, resolved_log_format


def test_json_lines_carry_level_timestamp_and_bound_ids(logs) -> None:  # type: ignore[no-untyped-def]
    log = get_logger("t")
    with log_context(request_id="req-1", job_id="job-9", case_id="case-3", run_id=None):
        log.info("step.done", step="decide")
    (line,) = logs.lines()
    assert line["event"] == "step.done" and line["level"] == "info" and line["step"] == "decide"
    assert line["request_id"] == "req-1" and line["job_id"] == "job-9"
    assert line["case_id"] == "case-3"
    assert "run_id" not in line  # None values are skipped
    assert line["timestamp"].endswith("Z")


def test_ids_are_restored_after_a_nested_block(logs) -> None:  # type: ignore[no-untyped-def]
    with log_context(request_id="outer"):
        with log_context(job_id="inner"):
            assert current_context() == {"request_id": "outer", "job_id": "inner"}
        assert current_context() == {"request_id": "outer"}
    assert current_context() == {}


def test_reset_context_drops_everything(logs) -> None:  # type: ignore[no-untyped-def]
    with log_context(request_id="x"):
        reset_context()
        assert current_context() == {}


def test_a_session_id_and_an_invite_code_never_reach_the_output(logs) -> None:  # type: ignore[no-untyped-def]
    session = secrets.token_urlsafe(32)
    invite = "cso-deadbeef-" + secrets.token_urlsafe(24)
    log = get_logger("auth")
    log.info("login", session_id=session, invite_code=invite)
    log.info(f"login attempt with {invite}", headers={"cookie": f"cso_session={session}"})
    log.warning("odd", detail={"note": f"token {session} seen"}, user="Alice Mapper")
    try:
        raise ValueError(f"bad code {invite}")
    except ValueError:
        log.exception("handler.failed")
    assert session not in logs.text and invite not in logs.text
    assert "Alice" not in logs.text
    assert logs.events("handler.failed")  # the line itself is still written


def test_exception_tracebacks_are_written_and_scrubbed(logs) -> None:  # type: ignore[no-untyped-def]
    invite = "cso-cafef00d-" + secrets.token_urlsafe(24)
    try:
        raise RuntimeError(invite)
    except RuntimeError:
        get_logger("x").exception("boom")
    (line,) = logs.events("boom")
    assert "RuntimeError" in line["exception"] and invite not in line["exception"]


def test_levels_below_the_threshold_are_dropped() -> None:
    stream = io.StringIO()
    configure_logging(fmt="json", level="WARNING", stream=stream, force=True)
    try:
        log = get_logger("lvl")
        log.info("quiet")
        log.warning("loud")
        assert "quiet" not in stream.getvalue() and "loud" in stream.getvalue()
    finally:
        structlog.reset_defaults()
        obs_logging._configured = None


def test_console_format_is_not_json_but_still_redacted() -> None:
    stream = io.StringIO()
    configure_logging(fmt="console", level="INFO", stream=stream, force=True)
    try:
        get_logger("c").info("hello", session_id="secret-value-123")
        out = stream.getvalue()
        assert "hello" in out and not out.lstrip().startswith("{")
        assert "secret-value-123" not in out
    finally:
        structlog.reset_defaults()
        obs_logging._configured = None


def test_configuring_twice_with_the_same_settings_does_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[int] = []
    monkeypatch.setattr(structlog, "configure", lambda **kw: calls.append(1))
    monkeypatch.setattr(obs_logging, "_configured", None)
    configure_logging(fmt="json", level="INFO")
    configure_logging(fmt="json", level="INFO")
    configure_logging(fmt="console", level="INFO")
    assert len(calls) == 2
    monkeypatch.setattr(obs_logging, "_configured", None)


def test_format_is_json_in_live_mode_and_console_in_replay() -> None:
    live = Settings(mode="live", user_agent="CSO/0.1 (+https://example.org/x; a@b.org)")
    replay = Settings(mode="replay")
    assert resolved_log_format(live) == "json"
    assert resolved_log_format(replay) == "console"
    assert resolved_log_format(Settings(mode="replay", log_format="json")) == "json"
    assert (
        resolved_log_format(Settings(mode="live", log_format="console", user_agent=live.user_agent))
        == "console"
    )


def test_default_destination_follows_the_current_stdout_not_the_one_at_configure_time(
    monkeypatch,
) -> None:
    import sys

    first = io.StringIO()
    monkeypatch.setattr(sys, "stdout", first)
    configure_logging(fmt="json", level="INFO", force=True)  # no stream: resolved at each write
    try:
        first.close()  # what a test runner does with its capture stream
        second = io.StringIO()
        monkeypatch.setattr(sys, "stdout", second)
        get_logger("late").info("still works")
        assert "still works" in second.getvalue()
    finally:
        structlog.reset_defaults()
        obs_logging._configured = None

"""State machine, backoff, error classification, handler registry and the repo guards."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

import pytest
from jobs_support import ManualClock, enqueue_fixture, get_job
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.adapters.decider.errors import (
    DeciderBusy,
    DeciderSchemaError,
    DeciderStateTooLong,
    DeciderTimeout,
    DeciderUnavailable,
)
from cso.adapters.osm.errors import (
    BandwidthLimitError,
    ElementCapExceededError,
    NotAllowedError,
    NotFoundError,
    OsmTimeoutError,
    ParseError,
    RateLimitedError,
    Redacted403,
    UpstreamError,
    XmlSafetyError,
)
from cso.domain.enums import JobKind, JobStatus
from cso.jobs import (
    DeciderNotConfigured,
    HandlerRegistry,
    PermanentJobError,
    TransientJobError,
    Worker,
    backoff_seconds,
    can_transition,
    classify,
    default_registry,
    is_terminal,
)
from cso.jobs.states import ANALYZE_STEPS, RETRY_BACKOFF_S, TRANSITIONS, assert_transition
from cso.persistence.db import session_scope
from cso.persistence.repos import JobsRepo

Factory = async_sessionmaker[AsyncSession]


def test_the_state_machine_only_allows_documented_moves() -> None:
    assert can_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    assert can_transition(JobStatus.RUNNING, JobStatus.QUEUED)  # retry and lease expiry
    assert not can_transition(JobStatus.QUEUED, JobStatus.SUCCEEDED)  # must run first
    for terminal in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
        assert is_terminal(terminal) and TRANSITIONS[terminal] == frozenset()
    assert not is_terminal(JobStatus.QUEUED) and not is_terminal(JobStatus.RUNNING)
    with pytest.raises(ValueError, match="cannot move"):
        assert_transition(JobStatus.FAILED, JobStatus.QUEUED)


def test_steps_and_backoff_follow_the_documented_policy() -> None:
    assert ANALYZE_STEPS == ("fetch_evidence", "snapshot", "decide", "persist")
    assert RETRY_BACKOFF_S == (5.0, 20.0, 60.0)
    assert [backoff_seconds(n, 0.5) for n in (1, 2, 3)] == [5.0, 20.0, 60.0]
    assert backoff_seconds(9, 0.5) == 60.0  # capped at the last step
    for n, base in enumerate(RETRY_BACKOFF_S, start=1):
        assert backoff_seconds(n, 0.0) == pytest.approx(base * 0.8)
        assert backoff_seconds(n, 1.0) == pytest.approx(base * 1.2)


@pytest.mark.parametrize(
    ("error", "retry", "code"),
    [
        (DeciderUnavailable("down"), True, "decider_unavailable"),
        (DeciderTimeout("slow"), True, "decider_unavailable"),
        (DeciderBusy("full"), True, "decider_busy"),
        (DeciderSchemaError("bad", {}), False, "schema"),
        (DeciderStateTooLong("long"), False, "state_too_long"),
        (DeciderNotConfigured("none"), False, "decider_not_configured"),
        (NotFoundError("gone"), False, "osm_not_found"),
        (NotAllowedError("write"), False, "osm_not_allowed"),
        (Redacted403("hidden"), False, "osm_forbidden"),
        (ParseError("xml"), False, "osm_unreadable"),
        (XmlSafetyError("bomb"), False, "osm_unreadable"),
        (ElementCapExceededError("big", limit=5000), False, "osm_unreadable"),
        (BandwidthLimitError("509", status=509), True, "osm_bandwidth_limit"),
        (RateLimitedError("429", status=429), True, "osm_unavailable"),
        (UpstreamError("503", status=503), True, "osm_unavailable"),
        (OsmTimeoutError("slow"), True, "osm_unavailable"),
        (TimeoutError("hard cap"), True, "job_timeout"),
        (RuntimeError("anything else"), True, "internal_error"),
        (TransientJobError("custom", "try later"), True, "custom"),
        (PermanentJobError("custom", "never"), False, "custom"),
    ],
)
def test_failures_classify_into_retry_or_terminal(error: Exception, retry: bool, code: str) -> None:
    verdict = classify(error)
    assert (verdict.retry, verdict.code) == (retry, code)


def test_the_stored_error_is_only_the_short_code() -> None:
    verdict = classify(RuntimeError("secret detail that must stay in the log"))
    assert verdict.code == "internal_error" and "secret" in verdict.detail  # detail is for logs


def test_registry_has_both_kinds_and_rejects_unknown_ones() -> None:
    registry = default_registry()
    assert registry.get(JobKind.ANALYZE) is not registry.get(JobKind.DRAFT)
    with pytest.raises(PermanentJobError, match="no handler"):
        HandlerRegistry().get(JobKind.ANALYZE)


async def test_list_for_case_is_ordered_and_filtered_by_kind(
    factory: Factory, clock: ManualClock
) -> None:
    case_id, first = await enqueue_fixture(factory, 2, clock)
    async with session_scope(factory) as session:
        repo = JobsRepo(session)
        clock.advance(1)
        draft, _ = await repo.enqueue(case_id, JobKind.DRAFT, response_type="x", now=clock())
        clock.advance(1)
        again, _ = await repo.enqueue(
            case_id, JobKind.ANALYZE, evidence_version="gen-1", now=clock()
        )
    async with factory() as session:
        repo = JobsRepo(session)
        everything = await repo.list_for_case(case_id)
        analyze = await repo.list_for_case(case_id, JobKind.ANALYZE)

    assert [j.id for j in everything] == [first, draft.id, again.id]
    assert [j.id for j in analyze] == [first, again.id]


async def test_finish_and_retry_require_the_owning_worker_when_asked(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    _, job_id = await enqueue_fixture(factory, 2, clock)
    claimed = await make_worker(worker_id="owner").claim()
    assert claimed is not None

    async with session_scope(factory) as session:
        repo = JobsRepo(session)
        assert not await repo.finish(job_id, JobStatus.SUCCEEDED, worker_id="intruder")
        assert not await repo.release_for_retry(
            job_id, error="x", run_after=clock() + timedelta(seconds=5), worker_id="intruder"
        )
        assert not await repo.set_progress(job_id, {"snapshot_id": "s"}, "intruder")
    assert (await get_job(factory, job_id)).status == JobStatus.RUNNING.value

    async with session_scope(factory) as session:
        repo = JobsRepo(session)
        assert await repo.set_progress(job_id, {"snapshot_id": "s"}, "owner")
        assert await repo.finish(job_id, JobStatus.SUCCEEDED, worker_id="owner")
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value and job.locked_by is None
    async with session_scope(factory) as session:
        assert not await JobsRepo(session).set_progress(uuid4(), {}, "owner")  # unknown job

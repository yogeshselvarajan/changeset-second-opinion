"""Retry, backoff, terminal failure, timeouts and the rules_only fallback."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import timedelta

import anyio
import pytest
from jobs_support import (
    FIXTURES,
    CrashingProvider,
    FakePanelDecider,
    ManualClock,
    MissingProvider,
    audit_actions,
    config,
    enqueue_fixture,
    get_case,
    get_job,
    make_deps,
    runs_of,
    snapshot_count,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.adapters.decider.errors import (
    DeciderBusy,
    DeciderSchemaError,
    DeciderStateTooLong,
    DeciderTimeout,
    DeciderUnavailable,
)
from cso.domain.enums import CaseStatus, JobKind, JobStatus, Lane, Response, RunStatus
from cso.jobs import (
    Deps,
    HandlerRegistry,
    JobContext,
    UnavailableDecider,
    Worker,
    default_registry,
)
from cso.jobs.handlers import draft_not_available
from cso.persistence.db import session_scope
from cso.persistence.repos import JobsRepo

Factory = async_sessionmaker[AsyncSession]


async def test_a_crash_requeues_with_backoff_and_the_third_failure_is_terminal(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    provider = CrashingProvider(FIXTURES, crashes=3)
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(deps=make_deps(FakePanelDecider(config()[0]), provider))

    await worker.run_until_idle()
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.QUEUED.value and job.attempts == 1
    assert job.run_after > clock() and job.last_error == "internal_error"
    assert job.locked_by is None and job.lease_expires_at is None

    assert await worker.run_until_idle() == []  # not due yet: nothing runs before run_after
    clock.advance(5)
    await worker.run_until_idle()
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.QUEUED.value and job.attempts == 2
    assert job.run_after - clock() == timedelta(seconds=20)

    clock.advance(20)
    await worker.run_until_idle()
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.FAILED.value and job.attempts == 3
    assert job.last_error == "internal_error"
    assert await runs_of(factory, case_id) == []  # no evidence, so no run
    assert (await get_case(factory, case_id)).status == CaseStatus.NEW.value
    actions = await audit_actions(factory, case_id)
    assert actions == ["job.enqueued", "job.retry_scheduled", "job.retry_scheduled", "job.failed"]


@pytest.mark.parametrize(("rand", "seconds"), [(0.0, 4.0), (0.5, 5.0), (1.0, 6.0)])
async def test_backoff_is_jittered_within_twenty_percent(
    rand: float,
    seconds: float,
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
) -> None:
    _, job_id = await enqueue_fixture(factory, 2, clock)
    deps = make_deps(FakePanelDecider(config()[0]), CrashingProvider(FIXTURES, crashes=1))
    await make_worker(deps=deps, rng=lambda: rand).run_until_idle()

    job = await get_job(factory, job_id)
    assert (job.run_after - clock()).total_seconds() == pytest.approx(seconds, abs=1e-3)


async def test_transient_decider_failure_retries_and_then_succeeds(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    decider = FakePanelDecider(config()[0], failures=[DeciderTimeout("slow"), None])
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(deps=make_deps(decider))

    await worker.run_until_idle()
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.QUEUED.value and job.last_error == "decider_unavailable"
    assert await runs_of(factory, case_id) == []  # a retryable failure stores no run yet

    clock.advance(5)
    await worker.run_until_idle()

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value and job.attempts == 2
    (run,) = await runs_of(factory, case_id)
    assert run.status == RunStatus.SUCCEEDED.value
    assert decider.calls == 2


@pytest.mark.parametrize("error", [DeciderUnavailable("down"), DeciderBusy("queue full")])
async def test_exhausted_decider_retries_store_a_rules_only_run_and_fail_the_job(
    error: Exception, factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    decider = FakePanelDecider(config()[0], failures=[error, error, error])
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(deps=make_deps(decider))

    for _ in range(3):
        await worker.run_until_idle()
        clock.advance(60)

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.FAILED.value and job.attempts == 3
    (run,) = await runs_of(factory, case_id)
    assert run.status == RunStatus.FAILED.value
    assert run.lane == Lane.RULES_ONLY.value and run.response is None
    assert run.failure_reason == job.last_error
    assert "R6" in {hit["code"] for hit in run.rules_fired}  # "no model answer" is on record
    assert job.result_ref is not None and job.result_ref["run_id"] == str(run.id)
    assert run.receipt is not None and run.receipt["errors"] == [run.failure_reason]

    case = await get_case(factory, case_id)
    assert case.lane == Lane.RULES_ONLY.value and case.latest_run_id == run.id
    assert case.latest_snapshot_id == run.snapshot_id  # the evidence was kept
    assert await snapshot_count(factory, case_id) == 1  # and was not re-stored on each retry
    assert decider.calls == 3


async def test_a_failed_run_on_thin_coverage_keeps_every_rule_hit_and_the_stronger_lane(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    # Fixture 04 has deletions and thin coverage: R3 outranks the missing-model fallback,
    # so the lane stays insufficient_evidence, but the run is still a failed one with all hits.
    error = DeciderUnavailable("down")
    decider = FakePanelDecider(config()[0], failures=[error, error, error])
    case_id, job_id = await enqueue_fixture(factory, 4, clock)
    worker = make_worker(deps=make_deps(decider))

    for _ in range(3):
        await worker.run_until_idle()
        clock.advance(60)

    assert (await get_job(factory, job_id)).status == JobStatus.FAILED.value
    (run,) = await runs_of(factory, case_id)
    assert run.status == RunStatus.FAILED.value
    assert run.lane == Lane.INSUFFICIENT_EVIDENCE.value
    assert {"R1", "R3", "R6"} <= {hit["code"] for hit in run.rules_fired}


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (DeciderSchemaError("answer does not match the schema", {"raw": 1}), "schema"),
        (DeciderStateTooLong("input too long"), "state_too_long"),
    ],
)
async def test_schema_and_length_errors_fail_at_once_with_a_rules_only_run(
    error: Exception,
    code: str,
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
) -> None:
    decider = FakePanelDecider(config()[0], failures=[error])
    case_id, job_id = await enqueue_fixture(factory, 2, clock)

    await make_worker(deps=make_deps(decider)).run_until_idle()

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.FAILED.value and job.attempts == 1  # no retry
    assert job.last_error == code
    (run,) = await runs_of(factory, case_id)
    assert run.lane == Lane.RULES_ONLY.value and run.failure_reason == code
    assert await audit_actions(factory, case_id) == ["job.enqueued", "analysis.failed"]


async def test_no_decider_configured_falls_back_to_rules_without_retrying(
    factory: Factory, clock: ManualClock, deps: Deps, make_worker: Callable[..., Worker]
) -> None:
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(deps=dataclasses.replace(deps, decider=UnavailableDecider()))

    await worker.run_until_idle()

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.FAILED.value and job.attempts == 1
    assert job.last_error == "decider_not_configured"
    (run,) = await runs_of(factory, case_id)
    assert run.lane == Lane.RULES_ONLY.value and run.status == RunStatus.FAILED.value


async def test_a_missing_changeset_fails_permanently_without_a_run(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    deps = make_deps(FakePanelDecider(config()[0]), MissingProvider(FIXTURES))

    await make_worker(deps=deps).run_until_idle()

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.FAILED.value and job.attempts == 1
    assert job.last_error == "osm_not_found"
    assert await runs_of(factory, case_id) == []
    assert (await get_case(factory, case_id)).status == CaseStatus.NEW.value


async def test_the_hard_cap_turns_a_hung_step_into_a_retry(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    async def hang(_ctx: JobContext) -> None:
        await anyio.sleep(30)

    _, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(
        registry=HandlerRegistry({JobKind.ANALYZE: hang}), hard_caps={JobKind.ANALYZE: 0.05}
    )

    await worker.run_until_idle()

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.QUEUED.value and job.last_error == "job_timeout"
    assert job.attempts == 1 and job.locked_by is None


async def test_the_documented_hard_caps(make_worker: Callable[..., Worker]) -> None:
    from cso.jobs import HARD_CAP_S

    assert HARD_CAP_S[JobKind.ANALYZE] == 120.0 and HARD_CAP_S[JobKind.DRAFT] == 60.0


async def test_a_registry_without_a_drafting_handler_fails_draft_jobs_cleanly(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, analyze_job = await enqueue_fixture(factory, 2, clock)
    async with session_scope(factory) as session:
        draft, created = await JobsRepo(session).enqueue(
            case_id,
            JobKind.DRAFT,
            response_type=Response.WELCOME_AND_TIPS.value,
            now=clock(),
        )
    assert created

    # The default registry now drafts (see test_jobs_draft_handler); this keeps covering a registry
    # that has no drafting handler, which must fail the job cleanly and without a retry.
    registry = HandlerRegistry(
        {
            JobKind.ANALYZE: default_registry().get(JobKind.ANALYZE),
            JobKind.DRAFT: draft_not_available,
        }
    )
    await make_worker(registry=registry).run_until_idle()

    job = await get_job(factory, draft.id)
    assert job.status == JobStatus.FAILED.value and job.attempts == 1
    assert job.last_error == "draft_not_available"
    assert (await get_job(factory, analyze_job)).status == JobStatus.SUCCEEDED.value

"""Cancellation: queued jobs never run; running jobs stop at the next step boundary."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from jobs_support import (
    FakePanelDecider,
    ManualClock,
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

from cso.domain.enums import CaseStatus, JobStatus
from cso.jobs import Worker
from cso.persistence.db import session_scope
from cso.persistence.repos import JobsRepo

Factory = async_sessionmaker[AsyncSession]


async def _cancel(factory: Factory, job_id: UUID) -> None:
    async with session_scope(factory) as session:
        await JobsRepo(session).request_cancel(job_id)


async def test_a_queued_job_that_is_cancelled_never_runs(
    factory: Factory,
    clock: ManualClock,
    decider: FakePanelDecider,
    make_worker: Callable[..., Worker],
) -> None:
    _, job_id = await enqueue_fixture(factory, 2, clock)
    await _cancel(factory, job_id)

    outcomes = await make_worker().run_until_idle()

    assert outcomes == [] and decider.calls == 0
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.CANCELLED.value and job.attempts == 0


async def test_the_cancel_flag_is_honoured_before_the_first_step(
    factory: Factory,
    clock: ManualClock,
    decider: FakePanelDecider,
    make_worker: Callable[..., Worker],
) -> None:
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker()
    job = await worker.claim()
    assert job is not None
    await _cancel(factory, job_id)  # flagged while running

    outcome = await worker.process(job)

    assert outcome.status is JobStatus.CANCELLED
    assert decider.calls == 0 and await snapshot_count(factory, case_id) == 0
    assert (await get_case(factory, case_id)).status == CaseStatus.NEW.value  # nothing was done
    assert await audit_actions(factory, case_id) == ["job.enqueued", "job.cancelled"]


async def test_a_cancel_during_decide_stops_before_the_run_is_written(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    _, job_id = await enqueue_fixture(factory, 2, clock)

    async def cancel_mid_decide() -> None:
        await _cancel(factory, job_id)

    decider = FakePanelDecider(config()[0], on_call=cancel_mid_decide)
    case_id = (await get_job(factory, job_id)).case_id

    outcomes = await make_worker(deps=make_deps(decider)).run_until_idle()

    assert [o.status for o in outcomes] == [JobStatus.CANCELLED]
    assert decider.calls == 1  # the decide step itself was not interrupted
    assert await runs_of(factory, case_id) == []  # but nothing was persisted afterwards
    assert await snapshot_count(factory, case_id) == 1  # the evidence stays stored
    assert (await get_job(factory, job_id)).status == JobStatus.CANCELLED.value


async def test_cancelling_a_finished_job_changes_nothing(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    _, job_id = await enqueue_fixture(factory, 2, clock)
    await make_worker().run_until_idle()

    await _cancel(factory, job_id)

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value and job.cancel_requested is False

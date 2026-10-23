"""Lease expiry, the reaper, lease ownership and surviving a dead worker."""

from __future__ import annotations

from collections.abc import Callable

import anyio
from jobs_support import (
    FakePanelDecider,
    ManualClock,
    enqueue_fixture,
    get_job,
    runs_of,
    snapshot_count,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import JobKind, JobStatus
from cso.jobs import HandlerRegistry, JobContext, Worker, reap_once, reaper_loop
from cso.persistence.db import session_scope
from cso.persistence.repos import JobsRepo

Factory = async_sessionmaker[AsyncSession]


async def test_expired_lease_is_requeued_by_the_reaper_and_then_completes(
    factory: Factory,
    clock: ManualClock,
    decider: FakePanelDecider,
    make_worker: Callable[..., Worker],
) -> None:
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    dead = make_worker(worker_id="worker-that-died", lease_seconds=60)
    claimed = await dead.claim()  # the process dies right after claiming
    assert claimed is not None and claimed.attempts == 1

    result = await reap_once(factory, clock=clock)
    assert result.requeued == 0 and result.failed == 0  # lease still valid
    clock.advance(61)
    result = await reap_once(factory, clock=clock)
    assert (result.requeued, result.failed) == (1, 0)
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.QUEUED.value and job.attempts == 1 and job.locked_by is None

    await make_worker(worker_id="replacement").run_until_idle()  # a new process picks it up

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value and job.attempts == 2
    assert len(await runs_of(factory, case_id)) == 1
    assert decider.calls == 1


async def test_a_job_that_keeps_losing_its_lease_fails_once_attempts_are_used_up(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    _, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(lease_seconds=60)

    for _ in range(3):
        assert await worker.claim() is not None
        clock.advance(61)
        await reap_once(factory, clock=clock)

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.FAILED.value and job.attempts == 3
    assert job.last_error == "lease_expired"
    assert await worker.claim() is None


async def test_a_worker_that_lost_its_lease_cannot_finish_or_write_anything(
    factory: Factory,
    clock: ManualClock,
    decider: FakePanelDecider,
    make_worker: Callable[..., Worker],
) -> None:
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    slow = make_worker(worker_id="slow", lease_seconds=60)
    stale_job = await slow.claim()
    assert stale_job is not None
    clock.advance(61)
    await reap_once(factory, clock=clock)
    fast = make_worker(worker_id="fast")
    taken = await fast.claim()
    assert taken is not None and taken.locked_by == "fast"

    outcome = await slow.process(stale_job)  # the slow worker wakes up and tries to carry on

    assert outcome.status is JobStatus.RUNNING  # still held by the fast worker, untouched
    job = await get_job(factory, job_id)
    assert job.locked_by == "fast" and job.status == JobStatus.RUNNING.value
    assert decider.calls == 0 and await runs_of(factory, case_id) == []
    assert await snapshot_count(factory, case_id) == 0
    async with session_scope(factory) as session:
        finished = await JobsRepo(session).finish(
            job_id, JobStatus.SUCCEEDED, worker_id="slow", now=clock()
        )
    assert finished is False


async def test_each_step_extends_the_lease(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    seen: dict[str, object] = {}

    async def handler(ctx: JobContext) -> None:
        before = (await get_job(factory, ctx.job_id)).lease_expires_at
        clock.advance(200)
        await ctx.checkpoint("decide")
        after = (await get_job(factory, ctx.job_id)).lease_expires_at
        seen.update(before=before, after=after, now=clock())

    _, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(registry=HandlerRegistry({JobKind.ANALYZE: handler}))
    await worker.run_until_idle()

    before, after, now = seen["before"], seen["after"], seen["now"]
    assert before is not None and after is not None
    assert after > before  # pushed out from the old expiry
    assert (after - now).total_seconds() == 300  # type: ignore[operator]
    assert (await get_job(factory, job_id)).status == JobStatus.SUCCEEDED.value  # no finish needed


async def test_reaper_loop_runs_periodically_and_stops_when_cancelled(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    _, job_id = await enqueue_fixture(factory, 2, clock)
    assert await make_worker(lease_seconds=60).claim() is not None
    clock.advance(61)

    async with anyio.create_task_group() as tg:
        tg.start_soon(lambda: reaper_loop(factory, interval_s=0.01, clock=clock))
        with anyio.fail_after(5):
            while (await get_job(factory, job_id)).status != JobStatus.QUEUED.value:
                await anyio.sleep(0.01)
        tg.cancel_scope.cancel()

    assert (await get_job(factory, job_id)).attempts == 1

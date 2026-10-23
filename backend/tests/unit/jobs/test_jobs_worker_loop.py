"""The long-running loop: polling, stopping, the reaper alongside it and surviving DB hiccups."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import anyio
import pytest
from jobs_support import ManualClock, enqueue_fixture, get_job, runs_of
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import JobStatus
from cso.jobs import Worker, reap_once, reaper_loop

Factory = async_sessionmaker[AsyncSession]


async def _wait_for(
    factory: Factory, job_id: object, status: JobStatus, seconds: float = 8
) -> None:
    with anyio.fail_after(seconds):
        while (await get_job(factory, job_id)).status != status.value:  # type: ignore[arg-type]
            await anyio.sleep(0.01)


async def test_run_forever_processes_jobs_and_stops_on_the_event(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    worker = make_worker()
    stop = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run_forever, stop)
        case_id, job_id = await enqueue_fixture(factory, 2, clock)  # arrives while it is polling
        await _wait_for(factory, job_id, JobStatus.SUCCEEDED)
        stop.set()  # the group only exits once the loop and its reaper have stopped

    assert len(await runs_of(factory, case_id)) == 1


async def test_a_worker_started_after_a_crash_recovers_the_orphaned_job(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    assert await make_worker(worker_id="crashed", lease_seconds=60).claim() is not None
    clock.advance(61)  # the lease ran out while no process was alive

    worker = make_worker(worker_id="restarted")
    stop = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run_forever, stop)  # its own reaper re-queues the job
        await _wait_for(factory, job_id, JobStatus.SUCCEEDED)
        stop.set()

    job = await get_job(factory, job_id)
    assert job.attempts == 2 and len(await runs_of(factory, case_id)) == 1


async def test_the_loop_survives_claim_errors(
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def instant(_seconds: float) -> None:
        await anyio.sleep(0.001)

    worker = make_worker(sleep=instant)
    real_claim = worker.claim
    failures = {"left": 2}

    async def flaky_claim() -> object:
        if failures["left"]:
            failures["left"] -= 1
            raise ConnectionError("database is restarting")
        return await real_claim()

    monkeypatch.setattr(worker, "claim", flaky_claim)
    _, job_id = await enqueue_fixture(factory, 2, clock)
    stop = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run_forever, stop)
        await _wait_for(factory, job_id, JobStatus.SUCCEEDED)
        stop.set()

    assert failures["left"] == 0


async def test_run_once_returns_none_when_nothing_is_due(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    worker = make_worker()
    assert await worker.run_once() is None

    _, job_id = await enqueue_fixture(factory, 2, clock)
    outcome = await worker.run_once()

    assert outcome is not None and outcome.job_id == job_id
    assert outcome.status is JobStatus.SUCCEEDED and outcome.result_ref is not None
    assert await worker.run_once() is None


async def test_reaping_with_nothing_expired_is_a_no_op(factory: Factory) -> None:
    result = await reap_once(factory)
    assert (result.requeued, result.failed) == (0, 0)


async def test_stopping_straight_after_starting_leaves_no_half_closed_connection(
    make_worker: Callable[..., Worker],
) -> None:
    # Regression: cancelling the reaper in the middle of a query left a connection being
    # terminated forever, which hung the event loop at shutdown. A stop signal lets it finish.
    worker = make_worker(reaper_interval_s=0.001)
    stop = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run_forever, stop)
        await anyio.sleep(0.05)  # the first reaper passes and claims are in flight
        stop.set()

    await asyncio.sleep(0.05)
    leftovers = [
        t.get_coro().__qualname__  # type: ignore[union-attr]
        for t in asyncio.all_tasks()
        if t is not asyncio.current_task()
    ]
    assert not [name for name in leftovers if "terminate" in name]


async def test_the_reaper_stops_promptly_on_its_stop_signal(factory: Factory) -> None:
    stop = anyio.Event()
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(lambda: reaper_loop(factory, interval_s=3600, stop=stop))
            await anyio.sleep(0.05)
            stop.set()  # a one-hour interval must not delay shutdown

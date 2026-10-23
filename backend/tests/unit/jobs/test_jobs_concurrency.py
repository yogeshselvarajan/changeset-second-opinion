"""Concurrency: Decider calls never overlap; two workers never run the same job twice."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

from jobs_support import (
    CASES,
    FIXTURES,
    AliasProvider,
    FakePanelDecider,
    ManualClock,
    config,
    get_job,
    make_deps,
    runs_of,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import JobStatus
from cso.jobs import Worker, enqueue_changeset
from cso.persistence.db import session_scope

Factory = async_sessionmaker[AsyncSession]

FIXTURE_NAMES = sorted(p.name for p in CASES.iterdir() if p.is_dir())


def _aliases(count: int) -> dict[int, str]:
    return {1000 + i: FIXTURE_NAMES[i % len(FIXTURE_NAMES)] for i in range(count)}


async def _queue(factory: Factory, clock: ManualClock, count: int) -> list[tuple[UUID, UUID]]:
    queued: list[tuple[UUID, UUID]] = []
    for i in range(count):
        async with session_scope(factory) as session:
            result = await enqueue_changeset(session, 1000 + i, now=clock())
        queued.append((result.case.id, result.job.id))
    return queued


async def test_ten_concurrent_analyses_never_overlap_decider_calls(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    decider = FakePanelDecider(config()[0], delay=0.01)  # a wait inside the call invites overlap
    provider = AliasProvider(FIXTURES, _aliases(10))
    queued = await _queue(factory, clock, 10)
    worker = make_worker(deps=make_deps(decider, provider), concurrency=4)

    outcomes = await worker.run_until_idle()

    assert len(outcomes) == 10 and all(o.status is JobStatus.SUCCEEDED for o in outcomes)
    assert decider.calls == 10
    assert decider.max_active == 1  # the fake asserts single flight: it never saw two at once
    for case_id, job_id in queued:
        assert (await get_job(factory, job_id)).attempts == 1
        assert len(await runs_of(factory, case_id)) == 1


async def test_two_workers_share_the_queue_without_running_a_job_twice(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    decider = FakePanelDecider(config()[0], delay=0.005)
    deps = make_deps(decider, AliasProvider(FIXTURES, _aliases(6)))
    queued = await _queue(factory, clock, 6)
    first = make_worker(deps=deps, worker_id="worker-a", concurrency=2)
    second = make_worker(deps=deps, worker_id="worker-b", concurrency=2)

    a, b = await asyncio.gather(first.run_until_idle(), second.run_until_idle())

    ran = [o.job_id for o in a] + [o.job_id for o in b]
    assert sorted(map(str, ran)) == sorted(str(job_id) for _, job_id in queued)  # each exactly once
    assert decider.calls == 6 and decider.max_active == 1
    for _, job_id in queued:
        job = await get_job(factory, job_id)
        assert job.status == JobStatus.SUCCEEDED.value and job.attempts == 1


async def test_default_concurrency_is_two_for_fetch_stages(
    make_worker: Callable[..., Worker],
) -> None:
    from cso.jobs.states import DEFAULT_CONCURRENCY

    assert DEFAULT_CONCURRENCY == 2
    assert make_worker().concurrency == 2
    assert make_worker(concurrency=0).concurrency == 1  # never below one slot

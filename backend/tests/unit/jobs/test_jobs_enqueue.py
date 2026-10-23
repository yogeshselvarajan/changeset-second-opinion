"""Idempotent enqueue: one job per generation, existing id while running, races, force."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from jobs_support import ManualClock, audit_actions, get_case, get_job
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import CaseStatus, JobKind, JobStatus
from cso.jobs import Worker, enqueue_analysis, enqueue_changeset
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, JobsRepo

Factory = async_sessionmaker[AsyncSession]
CHANGESET = 900000000002


async def test_enqueue_twice_gives_one_job_and_one_case(
    factory: Factory, clock: ManualClock
) -> None:
    async with session_scope(factory) as session:
        first = await enqueue_changeset(session, CHANGESET, now=clock())
    async with session_scope(factory) as session:
        second = await enqueue_changeset(session, CHANGESET, now=clock())

    assert first.created and first.case_created
    assert not second.created and not second.case_created
    assert second.job.id == first.job.id and second.case.id == first.case.id
    case = await get_case(factory, first.case.id)
    assert case.status == CaseStatus.ANALYZING.value
    assert await audit_actions(factory, first.case.id) == ["job.enqueued"]


async def test_a_request_while_the_job_runs_gets_the_existing_id(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    async with session_scope(factory) as session:
        queued = await enqueue_changeset(session, CHANGESET, now=clock())
    claimed = await make_worker().claim()
    assert claimed is not None and claimed.status == JobStatus.RUNNING.value

    async with session_scope(factory) as session:
        job, created = await enqueue_analysis(session, queued.case.id, now=clock())
        forced, forced_created = await enqueue_analysis(
            session, queued.case.id, force=True, now=clock()
        )

    assert not created and job.id == queued.job.id
    assert not forced_created and forced.id == queued.job.id  # force does not double-run either


async def test_a_succeeded_job_is_returned_unless_forced(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    async with session_scope(factory) as session:
        queued = await enqueue_changeset(session, CHANGESET, now=clock())
    await make_worker().run_until_idle()
    assert (await get_job(factory, queued.job.id)).status == JobStatus.SUCCEEDED.value

    async with session_scope(factory) as session:
        same, created = await enqueue_analysis(session, queued.case.id, now=clock())
    assert not created and same.id == queued.job.id

    async with session_scope(factory) as session:
        again, created = await enqueue_analysis(session, queued.case.id, force=True, now=clock())
    assert created and again.id != queued.job.id
    assert again.evidence_version == "gen-1" and again.kind == JobKind.ANALYZE.value


async def test_failed_and_cancelled_jobs_get_a_fresh_generation(
    factory: Factory, clock: ManualClock
) -> None:
    async with session_scope(factory) as session:
        queued = await enqueue_changeset(session, CHANGESET, now=clock())
    async with session_scope(factory) as session:
        await JobsRepo(session).finish(queued.job.id, JobStatus.FAILED, error="boom")

    async with session_scope(factory) as session:
        second, created = await enqueue_analysis(session, queued.case.id, now=clock())
    assert created and second.evidence_version == "gen-1"

    async with session_scope(factory) as session:
        await JobsRepo(session).request_cancel(second.id)
    async with session_scope(factory) as session:
        third, created = await enqueue_analysis(session, queued.case.id, now=clock())
    assert created and third.evidence_version == "gen-2"
    keys = {queued.job.job_key, second.job_key, third.job_key}
    assert len(keys) == 3


async def test_racing_enqueues_still_make_exactly_one_job(
    factory: Factory, clock: ManualClock
) -> None:
    async with session_scope(factory) as session:
        case, _ = await CasesRepo(session).get_or_create(CHANGESET, now=clock())

    async def attempt() -> tuple[str, bool]:
        async with session_scope(factory) as session:
            job, created = await enqueue_analysis(session, case.id, now=clock())
            return str(job.id), created

    results = await asyncio.gather(*(attempt() for _ in range(6)))

    assert len({job_id for job_id, _ in results}) == 1
    assert sum(1 for _, created in results if created) == 1
    async with factory() as session:
        jobs = await JobsRepo(session).list_for_case(case.id, JobKind.ANALYZE)
    assert len(jobs) == 1

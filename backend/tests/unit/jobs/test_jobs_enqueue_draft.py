"""`enqueue_draft`: one job per (run, response type) and generation, even when requests race."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import sqlalchemy as sa
from jobs_support import ManualClock, enqueue_fixture
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import JobKind, JobStatus
from cso.jobs import enqueue_draft
from cso.persistence.db import session_scope
from cso.persistence.repos import JobsRepo
from cso.persistence.tables import AuditEventRow, JobRow

Factory = async_sessionmaker[AsyncSession]
WELCOME = "welcome_and_tips"


async def _draft(
    factory: Factory, case_id: UUID, run_id: UUID, response_type: str = WELCOME, **kw: bool
) -> tuple[UUID, bool]:
    async with session_scope(factory) as session:
        job, created = await enqueue_draft(session, case_id, run_id, response_type, **kw)
        return job.id, created


async def _status(factory: Factory, job_id: UUID, status: JobStatus) -> None:
    async with session_scope(factory) as session:
        await session.execute(
            sa.update(JobRow).where(JobRow.id == job_id).values(status=status.value)
        )


async def test_a_queued_draft_job_is_returned_as_is(factory: Factory, clock: ManualClock) -> None:
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    run_id = uuid4()
    first, created = await _draft(factory, case_id, run_id)
    again, created_again = await _draft(factory, case_id, run_id)
    regenerate, created_regenerate = await _draft(factory, case_id, run_id, regenerate=True)
    assert created and not created_again and not created_regenerate
    assert first == again == regenerate
    async with session_scope(factory) as session:
        job = await JobsRepo(session).get(first)
        assert job is not None and job.kind == JobKind.DRAFT.value
        assert job.run_id == run_id and job.response_type == WELCOME


async def test_generations_follow_the_job_state(factory: Factory, clock: ManualClock) -> None:
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    run_id = uuid4()
    first, _ = await _draft(factory, case_id, run_id)

    await _status(factory, first, JobStatus.SUCCEEDED)
    same, created = await _draft(factory, case_id, run_id)
    assert same == first and not created  # finished drafts are not redone

    regenerated, created = await _draft(factory, case_id, run_id, regenerate=True)
    assert created and regenerated != first
    await _status(factory, regenerated, JobStatus.FAILED)
    retried, created = await _draft(factory, case_id, run_id)
    assert created and retried not in {first, regenerated}  # a failed job gets a new generation


async def test_other_runs_and_response_types_get_their_own_jobs(
    factory: Factory, clock: ManualClock
) -> None:
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    run_a, run_b = uuid4(), uuid4()
    ids = {
        (await _draft(factory, case_id, run_a))[0],
        (await _draft(factory, case_id, run_b))[0],
        (await _draft(factory, case_id, run_a, "ask_source_question"))[0],
    }
    assert len(ids) == 3


async def test_racing_requests_create_one_job_and_one_audit_event(
    factory: Factory, clock: ManualClock
) -> None:
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    run_id = uuid4()
    results = await asyncio.gather(*[_draft(factory, case_id, run_id) for _ in range(5)])
    assert len({job_id for job_id, _ in results}) == 1
    assert sum(1 for _, created in results if created) == 1
    async with session_scope(factory) as session:
        events = (
            await session.execute(
                sa.select(AuditEventRow.payload).where(AuditEventRow.action == "job.enqueued")
            )
        ).scalars()
        drafts = [p for p in events if p.get("kind") == "draft"]
    assert len(drafts) == 1 and drafts[0]["response_type"] == WELCOME

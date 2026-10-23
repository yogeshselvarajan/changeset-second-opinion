"""Idempotent enqueue of analysis jobs (the only entry point the API uses).

The job key is (case, kind, evidence_version, run_id, response_type). The evidence version of an
analyze job is not known until the worker has fetched evidence, so that slot holds a generation
marker instead: None for the first job of a case, `gen-<n>` for every later one. The real evidence
version ends up in the run. `UNIQUE(job_key)` then gives exactly one job per generation, even when
two requests race.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.enums import CaseStatus, JobKind, JobStatus
from cso.persistence.repos import AuditRepo, CasesRepo, JobsRepo
from cso.persistence.repos.jobs_repo import make_job_key
from cso.persistence.tables import JobRow, ReviewCaseRow


@dataclass(frozen=True)
class EnqueueResult:
    """A case and the analyze job that covers it; `created` is False for an existing job."""

    case: ReviewCaseRow
    job: JobRow
    created: bool
    case_created: bool = False


def _generation_marker(generation: int) -> str | None:
    return None if generation == 0 else f"gen-{generation}"


async def enqueue_analysis(
    session: AsyncSession,
    case_id: UUID,
    *,
    force: bool = False,
    actor: str = "system",
    request_id: str | None = None,
    now: datetime | None = None,
) -> tuple[JobRow, bool]:
    """Queue an analysis of the case unless one is already queued, running or (without force) done.

    Returns `(job, created)`. A queued or running job is always returned as is, so a request that
    arrives while the job runs gets the existing id. A succeeded job is returned unless `force`;
    a failed or cancelled one gets a fresh generation.
    """
    cid = case_id
    jobs = JobsRepo(session)
    history = await jobs.list_for_case(cid, JobKind.ANALYZE)
    for job in history:
        if job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
            return job, False
    if history and not force and history[-1].status == JobStatus.SUCCEEDED.value:
        return history[-1], False

    marker = _generation_marker(len(history))
    created = True
    try:
        async with session.begin_nested():
            job, created = await jobs.enqueue(
                cid, JobKind.ANALYZE, evidence_version=marker, request_id=request_id, now=now
            )
    except IntegrityError:  # a concurrent request inserted the same generation first
        existing = await jobs.get_by_key(make_job_key(cid, JobKind.ANALYZE, marker, None, None))
        if existing is None:
            raise
        return existing, False
    if created:
        cases = CasesRepo(session)
        case = await cases.get(cid)
        if case is not None and case.status == CaseStatus.NEW.value:
            await cases.set_status(cid, CaseStatus.ANALYZING, now=now)
        await AuditRepo(session).append(
            actor=actor,
            action="job.enqueued",
            case_id=cid,
            payload={"job_id": str(job.id), "kind": JobKind.ANALYZE.value, "force": force},
            now=now,
        )
    return job, created


async def enqueue_changeset(
    session: AsyncSession,
    changeset_id: int,
    *,
    actor: str = "system",
    request_id: str | None = None,
    now: datetime | None = None,
) -> EnqueueResult:
    """Create the case for a changeset if needed and queue its analysis (POST /cases)."""
    case, case_created = await CasesRepo(session).get_or_create(changeset_id, now=now)
    job, created = await enqueue_analysis(
        session, case.id, actor=actor, request_id=request_id, now=now
    )
    return EnqueueResult(case=case, job=job, created=created, case_created=case_created)


async def enqueue_draft(
    session: AsyncSession,
    case_id: UUID,
    run_id: UUID,
    response_type: str,
    *,
    regenerate: bool = False,
    actor: str = "system",
    request_id: str | None = None,
    now: datetime | None = None,
) -> tuple[JobRow, bool]:
    """Queue a draft job for (run, response type) unless one is queued, running or done.

    Mirrors `enqueue_analysis`: the key is (case, draft, generation marker, run, response type), so
    two racing requests produce one job. A queued or running job is returned as is, a succeeded
    one is returned unless `regenerate`, and a failed or cancelled one gets a fresh generation.
    Returns `(job, created)`.
    """
    jobs = JobsRepo(session)
    history = [
        job
        for job in await jobs.list_for_case(case_id, JobKind.DRAFT)
        if job.run_id == run_id and job.response_type == response_type
    ]
    for job in history:
        if job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
            return job, False
    if history and not regenerate and history[-1].status == JobStatus.SUCCEEDED.value:
        return history[-1], False

    marker = _generation_marker(len(history))
    try:
        async with session.begin_nested():
            job, created = await jobs.enqueue(
                case_id,
                JobKind.DRAFT,
                evidence_version=marker,
                run_id=run_id,
                response_type=response_type,
                request_id=request_id,
                now=now,
            )
    except IntegrityError:  # a concurrent request inserted the same generation first
        existing = await jobs.get_by_key(
            make_job_key(case_id, JobKind.DRAFT, marker, run_id, response_type)
        )
        if existing is None:
            raise
        return existing, False
    if created:
        await AuditRepo(session).append(
            actor=actor,
            action="job.enqueued",
            case_id=case_id,
            payload={
                "job_id": str(job.id),
                "kind": JobKind.DRAFT.value,
                "run_id": str(run_id),
                "response_type": response_type,
                "regenerate": regenerate,
            },
            now=now,
        )
    return job, created

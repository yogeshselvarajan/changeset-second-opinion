"""Single records: a run with its receipt, a job (poll and cancel), a draft."""

from __future__ import annotations

from uuid import UUID

from fastapi import Request

from cso.api.db import SessionFactoryDep
from cso.api.mappers import analysis_run, draft_out, job_out
from cso.api.problems import ConflictError, NotFoundError, get_request_id, problem_responses
from cso.api.routing import Reviewer, Viewer, actor_of, make_router
from cso.api.schemas import AnalysisRun, Draft, Job
from cso.domain.enums import JobStatus
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo, DraftsRepo, JobsRepo, RunsRepo

router = make_router(tags=["records"])

_TERMINAL = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value)


@router.get(
    "/runs/{id}",
    response_model=AnalysisRun,
    summary="A run with its decision receipt",
    responses=problem_responses(404),
)
async def get_run(id: UUID, factory: SessionFactoryDep, principal: Viewer) -> AnalysisRun:
    """The run and the receipt that records how it was reached."""
    async with session_scope(factory) as session:
        row = await RunsRepo(session).get_row(id)
        if row is None:
            raise NotFoundError("The run does not exist.")
        run = analysis_run(row)
    if run is None:
        raise NotFoundError("The run has no stored receipt.")
    return run


@router.get(
    "/jobs/{id}",
    response_model=Job,
    summary="Status of a background job",
    responses=problem_responses(404),
)
async def get_job(id: UUID, factory: SessionFactoryDep, principal: Viewer) -> Job:
    """Poll about every two seconds; `result_ref` names the run or draft when it succeeded."""
    async with session_scope(factory) as session:
        row = await JobsRepo(session).get(id)
        if row is None:
            raise NotFoundError("The job does not exist.")
        return job_out(row)


@router.post(
    "/jobs/{id}/cancel",
    status_code=202,
    response_model=Job,
    summary="Ask for a job to end",
    responses=problem_responses(401, 403, 404, 409),
)
async def cancel_job(
    id: UUID, request: Request, factory: SessionFactoryDep, principal: Reviewer
) -> Job:
    """A queued job is cancelled at once; a running one ends at its next step. Repeats are fine."""
    async with session_scope(factory) as session:
        jobs = JobsRepo(session)
        existing = await jobs.get(id)
        if existing is None:
            raise NotFoundError("The job does not exist.")
        if existing.status in _TERMINAL:
            raise ConflictError("The job has already finished.", job_id=str(existing.id))
        if existing.status == JobStatus.CANCELLED.value or existing.cancel_requested:
            return job_out(existing)
        row = await jobs.request_cancel(id)
        if row is None:
            raise NotFoundError("The job does not exist.")
        await AuditRepo(session).append(
            actor=actor_of(principal),
            action="job.cancel_requested",
            case_id=row.case_id,
            payload={"job_id": str(row.id), "status": row.status},
            request_id=get_request_id(request),
        )
        return job_out(row)


@router.get(
    "/drafts/{id}",
    response_model=Draft,
    summary="A draft comment with its validation result",
    responses=problem_responses(404),
)
async def get_draft(id: UUID, factory: SessionFactoryDep, principal: Viewer) -> Draft:
    """Draft text and the tone check it passed or failed."""
    async with session_scope(factory) as session:
        draft = await DraftsRepo(session).get(id)
    if draft is None:
        raise NotFoundError("The draft does not exist.")
    return draft_out(draft)

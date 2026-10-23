"""Things reviewers do to a case: request an analysis, request a draft, record an outcome."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cso.api.assemble import load_case_detail
from cso.api.db import SessionFactoryDep
from cso.api.deps import Principal
from cso.api.etag import format_etag, parse_if_match
from cso.api.mappers import draftable_responses, outcome_out
from cso.api.problems import (
    ConflictError,
    FinalTextInvalidError,
    NotFoundError,
    PreconditionFailedError,
    UnprocessableError,
    get_request_id,
    problem_responses,
)
from cso.api.routing import Reviewer, ReviewerFirst, actor_of, make_router
from cso.api.schemas import (
    AnalysisAccepted,
    AnalysisCurrent,
    AnalysisRequest,
    CaseDetail,
    DraftAccepted,
    DraftRequest,
    OutcomeInput,
)
from cso.api.security import analysis_quota, draft_quota
from cso.domain.calibration import COMPOSED_PROBES
from cso.domain.config import CommunityConfig, ConfigError, Tone
from cso.domain.draft_validation import validate_final_text
from cso.domain.enums import Disposition, JobKind, JobStatus
from cso.jobs import enqueue_analysis, enqueue_draft
from cso.observability.budget import analysis_cap, draft_cap
from cso.persistence.db import session_scope
from cso.persistence.errors import VersionConflictError
from cso.persistence.repos import (
    AuditRepo,
    CasesRepo,
    ConfigsRepo,
    JobsRepo,
    OutcomesRepo,
    RunsRepo,
)

router = make_router(tags=["actions"])

_ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
_NO_BODY = AnalysisRequest()


def _session_id(principal: Principal) -> UUID | None:
    """The session behind the caller, when the auth layer provides one."""
    raw: Any = getattr(principal, "session_id", None)
    if raw is None:
        return None
    try:
        return raw if isinstance(raw, UUID) else UUID(str(raw))
    except ValueError:
        return None


@router.post(
    "/cases/{id}/analyses",
    status_code=202,
    response_model=AnalysisAccepted,
    summary="Request an analysis",
    dependencies=[ReviewerFirst, Depends(analysis_quota), Depends(analysis_cap)],
    responses={
        200: {"model": AnalysisCurrent, "description": "The latest run is current"},
        **problem_responses(401, 403, 404, 429),
        409: {
            **problem_responses(409)[409],
            "description": (
                "An analysis is already queued or running. The problem carries the existing job's "
                "id in the extension member `job_id`."
            ),
        },
    },
)
async def request_analysis(
    id: UUID,
    request: Request,
    factory: SessionFactoryDep,
    principal: Reviewer,
    body: AnalysisRequest = _NO_BODY,
) -> AnalysisAccepted | JSONResponse:
    """202 with the job id; 200 with the run id when the latest run is current and not forced."""
    async with session_scope(factory) as session:
        case = await CasesRepo(session).get(id)
        if case is None:
            raise NotFoundError("The case does not exist.")
        if not body.force and not case.stale and case.latest_run_id is not None:
            analyses = await JobsRepo(session).list_for_case(id, JobKind.ANALYZE)
            if not any(job.status in _ACTIVE for job in analyses):
                current = AnalysisCurrent(run_id=case.latest_run_id)
                return JSONResponse(current.model_dump(mode="json"), status_code=200)
        # Changed evidence upstream (stale) is a reason to re-run even without `force`.
        job, created = await enqueue_analysis(
            session,
            id,
            force=body.force or case.stale,
            actor=actor_of(principal),
            request_id=get_request_id(request),
        )
        if not created and job.status in _ACTIVE:
            raise ConflictError("An analysis is already queued or running.", job_id=str(job.id))
        job_id = job.id
    return AnalysisAccepted(job_id=job_id)


@router.post(
    "/cases/{id}/drafts",
    status_code=202,
    response_model=DraftAccepted,
    summary="Request a draft comment",
    dependencies=[ReviewerFirst, Depends(draft_quota), Depends(draft_cap)],
    responses=problem_responses(401, 403, 404, 409, 429),
)
async def request_draft(
    id: UUID,
    request: Request,
    body: DraftRequest,
    factory: SessionFactoryDep,
    principal: Reviewer,
) -> DraftAccepted:
    """Queue a draft for a response type that the latest run allows; a person edits and posts it."""
    async with session_scope(factory) as session:
        case = await CasesRepo(session).get(id)
        if case is None:
            raise NotFoundError("The case does not exist.")
        run_row = (
            None
            if case.latest_run_id is None
            else await RunsRepo(session).get_row(case.latest_run_id)
        )
        if run_row is None:
            raise ConflictError("There is no analysis to draft from yet.")
        if case.stale:
            raise ConflictError(
                "The case changed since the latest analysis; request a new analysis first.",
                allowed=[],
            )
        allowed = draftable_responses(case, run_row)  # the rule `CaseDetail.allowed_responses` uses
        if body.response_type not in allowed:
            raise ConflictError(
                "The latest analysis does not suggest this kind of comment.",
                allowed=[r.value for r in allowed],
            )
        job, _ = await enqueue_draft(
            session,
            id,
            run_row.id,
            body.response_type.value,
            regenerate=body.regenerate,
            actor=actor_of(principal),
            request_id=get_request_id(request),
        )
        job_id = job.id
    return DraftAccepted(job_id=job_id)


async def _active_tone(session: AsyncSession) -> Tone:
    """The tone rules of the active stored configuration, else of the default one."""
    row = await ConfigsRepo(session).get_active()
    if row is not None:
        try:
            return CommunityConfig.from_yaml_text(
                row.yaml, source=f"stored config {row.version}"
            ).tone
        except ConfigError:
            pass  # a stored version that no longer validates must not open the check; use default
    return CommunityConfig.load().tone


@router.put(
    "/cases/{id}/outcome",
    response_model=CaseDetail,
    summary="Record what the reviewer decided",
    responses=problem_responses(400, 401, 403, 404, 412, 422, 428),
)
async def put_outcome(
    id: UUID,
    body: OutcomeInput,
    request: Request,
    response: Response,
    factory: SessionFactoryDep,
    principal: Reviewer,
    if_match: Annotated[
        str | None,
        Header(description='Outcome version last seen, as W/"<outcome_version>"'),
    ] = None,
) -> CaseDetail:
    """Append an outcome; send `If-Match` with the `outcome_version` you saw (428 if missing)."""
    expected = parse_if_match(if_match)
    if body.probe_corrections:
        # Corrections say which facts were wrong; they only make sense on a disagreement, and only
        # for the probes that feed the suggestion.
        if body.disposition not in (
            Disposition.DISAGREE_WITH_MODEL,
            Disposition.DIFFERENT_RESPONSE,
        ):
            raise UnprocessableError("Corrections are only accepted on a disagreement.")
        if not set(body.probe_corrections) <= set(COMPOSED_PROBES):
            raise UnprocessableError("A correction names a fact that is not part of the panel.")
    async with session_scope(factory) as session:
        if body.final_text is not None:
            violations = validate_final_text(body.final_text, await _active_tone(session))
            if violations:  # nothing is stored; the codes never repeat the offending text
                raise FinalTextInvalidError(
                    "The comment text does not meet the drafting rules.",
                    violations=violations,
                )
        cases = CasesRepo(session)
        case = await cases.get(id)
        if case is None:
            raise NotFoundError("The case does not exist.")
        seen = await RunsRepo(session).get_row(body.run_id_seen)
        if seen is None or seen.case_id != case.id:
            raise UnprocessableError("run_id_seen is not a run of this case.")
        outcomes = OutcomesRepo(session)
        try:
            stored = await outcomes.append(
                case.id,
                body,
                reviewer_display=principal.display_name or principal.id,
                session_id=_session_id(principal),
                expected_version=expected,
                identity_id=principal.identity_id,
            )
        except VersionConflictError as exc:
            latest = await outcomes.latest_for_case(case.id)
            raise PreconditionFailedError(
                "The case changed since you loaded it. Review the current record and try again.",
                current={
                    "outcome_version": exc.current,
                    "outcome": None
                    if latest is None
                    else outcome_out(latest).model_dump(mode="json"),
                },
            ) from exc
        await AuditRepo(session).append(
            actor=actor_of(principal),
            action="outcome.recorded",
            case_id=case.id,
            session_id=_session_id(principal),
            payload={
                "outcome_id": str(stored.id),
                "disposition": stored.disposition.value,
                "run_id_seen": str(stored.run_id_seen),
            },
            request_id=get_request_id(request),
        )
        await session.refresh(case)  # the version bump was a bulk UPDATE
        detail = await load_case_detail(session, case)
    response.headers["ETag"] = format_etag(detail.outcome_version)
    return detail

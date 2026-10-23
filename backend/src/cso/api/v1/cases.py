"""Cases: queue listing, create, bulk import, detail, evidence, runs and audit (contract §2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request, Response

from cso.api.assemble import load_case_detail, load_evidence
from cso.api.db import SessionFactoryDep, SettingsDep
from cso.api.deps import get_optional_principal
from cso.api.etag import format_etag
from cso.api.mappers import (
    audit_cursor,
    audit_out,
    case_summary,
    from_keyset,
    run_summary,
    to_keyset,
)
from cso.api.pagination import decode_cursor, encode_cursor
from cso.api.problems import (
    InvalidCursorError,
    InvalidParameterError,
    NotFoundError,
    UpstreamUnavailableError,
    get_request_id,
    problem_responses,
)
from cso.api.routing import Reviewer, ReviewerFirst, Viewer, actor_of, make_router
from cso.api.schemas import (
    CHANGESET_ID_MAX,
    AuditListQuery,
    AuditListResponse,
    CaseCreated,
    CaseDetail,
    CaseListQuery,
    CaseListResponse,
    CaseRunsResponse,
    CreateCaseRequest,
    EvidenceQuery,
    EvidenceSnapshot,
    ImportAccepted,
    ImportRequest,
)
from cso.api.security import analysis_quota, charge_quota
from cso.domain.enums import JobKind, JobStatus
from cso.jobs import enqueue_changeset
from cso.jobs.imports import (
    ChallengeImportUnavailable,
    ChallengeLister,
    ChallengeSourceError,
    build_challenge_lister,
)
from cso.observability.budget import BudgetGuard, analysis_cap
from cso.persistence.db import session_scope
from cso.persistence.repos import (
    AuditRepo,
    CaseFilters,
    CasesRepo,
    RunsRepo,
    SnapshotsRepo,
)

router = make_router(tags=["cases"])

_ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


async def get_challenge_lister(settings: SettingsDep) -> AsyncIterator[ChallengeLister]:
    """The challenge source for the current mode, closed after the request."""
    lister = build_challenge_lister(settings)
    try:
        yield lister
    finally:
        await lister.aclose()


# --------------------------------------------------------------------------- queue


@router.get(
    "/cases",
    response_model=CaseListResponse,
    summary="List cases in queue order",
    responses=problem_responses(400),
)
async def list_cases(
    query: Annotated[CaseListQuery, Query()],
    factory: SessionFactoryDep,
    principal: Viewer,
) -> CaseListResponse:
    """Cases ordered by lane, then newest first, with the size of every lane."""
    cursor = None if query.cursor is None else to_keyset(decode_cursor(query.cursor))
    filters = CaseFilters(
        lane=query.lane,
        status=query.status,
        editor=query.editor,
        q=query.q,
        stale=query.stale,
    )
    async with session_scope(factory) as session:
        cases = CasesRepo(session)
        page = await cases.list_page(filters, cursor, query.limit)
        counts = await cases.counts_by_lane(filters)
        run_ids = [row.latest_run_id for row in page.items if row.latest_run_id is not None]
        codes = await RunsRepo(session).rule_codes_by_id(run_ids)
        items = [
            case_summary(row, codes.get(row.latest_run_id, []) if row.latest_run_id else [])
            for row in page.items
        ]
    next_cursor = None if page.next_cursor is None else encode_cursor(from_keyset(page.next_cursor))
    return CaseListResponse(items=items, next_cursor=next_cursor, counts_by_lane=counts)


@router.post(
    "/cases",
    status_code=201,
    response_model=CaseCreated,
    summary="Create a case and queue its analysis",
    dependencies=[ReviewerFirst, Depends(analysis_quota), Depends(analysis_cap)],
    responses={
        200: {"model": CaseCreated, "description": "The case already existed"},
        **problem_responses(400, 401, 403, 429),
    },
)
async def create_case(
    body: CreateCaseRequest,
    request: Request,
    response: Response,
    factory: SessionFactoryDep,
    principal: Reviewer,
) -> CaseCreated:
    """Idempotent on the changeset id: 201 for a new case, 200 for an existing one."""
    async with session_scope(factory) as session:
        queued = await enqueue_changeset(
            session,
            body.changeset_id,
            actor=actor_of(principal),
            request_id=get_request_id(request),
        )
        if queued.case_created:
            await AuditRepo(session).append(
                actor=actor_of(principal),
                action="case.created",
                case_id=queued.case.id,
                payload={"changeset_id": body.changeset_id, "source": body.source},
                request_id=get_request_id(request),
            )
        detail = await load_case_detail(session, queued.case)
        job_active = queued.job.status in _ACTIVE
        job_id = queued.job.id if job_active else None
    response.status_code = 201 if queued.case_created else 200
    response.headers["ETag"] = format_etag(detail.outcome_version)
    return CaseCreated(case=detail, job_id=job_id)


@router.post(
    "/cases/import",
    status_code=202,
    response_model=ImportAccepted,
    summary="Create cases in bulk from a challenge or a list of ids",
    dependencies=[ReviewerFirst, Depends(analysis_quota), Depends(analysis_cap)],
    responses=problem_responses(400, 401, 403, 502),
)
async def import_cases(
    body: ImportRequest,
    request: Request,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    principal: Reviewer,
    lister: Annotated[ChallengeLister, Depends(get_challenge_lister)],
) -> ImportAccepted:
    """Idempotent per id: existing cases are counted, not duplicated."""
    # Each id may queue one analysis, so the call is charged per id (the docstring above is
    # published in the OpenAPI schema, so this note lives in a comment): the per-caller quota (one
    # token was taken by the dependency, the rest below) and the daily analysis cap (429 when
    # `used + ids` would pass it), both before anything is queued.
    ids: list[int] = list(dict.fromkeys(body.ids or []))
    if body.challenge_id is not None:
        if body.source != "maproulette":
            raise InvalidParameterError("challenge_id is only available for source maproulette.")
        try:
            fetched = await lister.list_changeset_ids(body.challenge_id, body.limit)
        except ChallengeImportUnavailable as exc:
            raise InvalidParameterError(str(exc)) from exc
        except ChallengeSourceError as exc:
            raise UpstreamUnavailableError("MapRoulette could not be read just now.") from exc
        known = set(ids)
        ids.extend(i for i in fetched if 1 <= i <= CHANGESET_ID_MAX and i not in known)
    ids = ids[: body.limit]
    if len(ids) > 1:
        charge_quota(request, await get_optional_principal(request), "analysis", len(ids) - 1)
    if ids:
        async with factory() as session:
            await BudgetGuard(settings).check(session, JobKind.ANALYZE, count=len(ids))

    created = existing = 0
    job_ids = []
    async with session_scope(factory) as session:
        for changeset_id in ids:
            queued = await enqueue_changeset(
                session,
                changeset_id,
                actor=actor_of(principal),
                request_id=get_request_id(request),
            )
            if queued.case_created:
                created += 1
                await AuditRepo(session).append(
                    actor=actor_of(principal),
                    action="case.created",
                    case_id=queued.case.id,
                    payload={"changeset_id": changeset_id, "source": body.source},
                    request_id=get_request_id(request),
                )
            else:
                existing += 1
            if queued.job.status in _ACTIVE:
                job_ids.append(queued.job.id)
    return ImportAccepted(created=created, existing=existing, job_ids=job_ids)


# --------------------------------------------------------------------------- one case


@router.get(
    "/cases/{id}",
    response_model=CaseDetail,
    summary="Case detail",
    responses=problem_responses(404),
)
async def get_case(
    id: UUID, response: Response, factory: SessionFactoryDep, principal: Viewer
) -> CaseDetail:
    """The case with its latest run, draft and outcome; `ETag` carries the outcome version."""
    async with session_scope(factory) as session:
        row = await CasesRepo(session).get(id)
        if row is None:
            raise NotFoundError("The case does not exist.")
        detail = await load_case_detail(session, row)
    response.headers["ETag"] = format_etag(detail.outcome_version)
    return detail


@router.get(
    "/cases/{id}/evidence",
    response_model=EvidenceSnapshot,
    summary="Evidence snapshot of a case",
    responses=problem_responses(404),
)
async def get_case_evidence(
    id: UUID,
    query: Annotated[EvidenceQuery, Query()],
    factory: SessionFactoryDep,
    principal: Viewer,
) -> EvidenceSnapshot:
    """The latest snapshot, or the one named by `snapshot_id`."""
    async with session_scope(factory) as session:
        if await CasesRepo(session).get(id) is None:
            raise NotFoundError("The case does not exist.")
        snapshots = SnapshotsRepo(session)
        if query.snapshot_id is not None:
            snapshot = await snapshots.get(query.snapshot_id)
            if snapshot is not None and snapshot.case_id != id:
                snapshot = None
        else:
            snapshot = await snapshots.latest_for_case(id)
        if snapshot is None:
            raise NotFoundError("There is no evidence snapshot for this case yet.")
        return await load_evidence(session, snapshot)


@router.get(
    "/cases/{id}/runs",
    response_model=CaseRunsResponse,
    summary="Runs of a case, newest first",
    responses=problem_responses(404),
)
async def list_case_runs(
    id: UUID, factory: SessionFactoryDep, principal: Viewer
) -> CaseRunsResponse:
    """Every analysis run of the case."""
    async with session_scope(factory) as session:
        if await CasesRepo(session).get(id) is None:
            raise NotFoundError("The case does not exist.")
        rows = await RunsRepo(session).list_rows_for_case(id)
        return CaseRunsResponse(items=[run_summary(row) for row in rows])


@router.get(
    "/cases/{id}/audit",
    response_model=AuditListResponse,
    summary="Audit events of a case",
    responses=problem_responses(404),
)
async def list_case_audit(
    id: UUID,
    query: Annotated[AuditListQuery, Query()],
    factory: SessionFactoryDep,
    principal: Viewer,
) -> AuditListResponse:
    """Events in order of occurrence; the cursor continues after the last event seen."""
    after_id: int | None = None
    if query.cursor is not None:
        after_id = decode_cursor(query.cursor).rank
        if after_id is None:
            raise InvalidCursorError("The cursor is not valid. Start again without a cursor.")
    async with session_scope(factory) as session:
        if await CasesRepo(session).get(id) is None:
            raise NotFoundError("The case does not exist.")
        page = await AuditRepo(session).list_for_case(id, after_id=after_id, limit=query.limit)
        items = [audit_out(row) for row in page.items]
        last = page.items[-1] if page.items else None
    next_cursor = (
        encode_cursor(audit_cursor(last)) if last is not None and page.next_after_id else None
    )
    return AuditListResponse(items=items, next_cursor=next_cursor)

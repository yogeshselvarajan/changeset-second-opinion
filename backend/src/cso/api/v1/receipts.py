"""The shareable decision receipt: public by design, with an allow-list of fields."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from cso.api.auth_core import client_ip, get_config
from cso.api.db import SessionFactoryDep
from cso.api.deps import Principal, get_optional_principal
from cso.api.mappers import public_receipt
from cso.api.problems import NotFoundError, RateLimitedError, problem_responses
from cso.api.routing import make_router
from cso.api.schemas import PublicReceipt
from cso.api.security import get_limiter, retry_after_headers
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, ConfigsRepo, RunsRepo

router = make_router(tags=["receipts"])

#: Requests per address per minute. The receipt is cheap to read but open to anyone with a link.
RECEIPT_PER_IP_MINUTE = 60


@router.get(
    "/receipts/{run_id}",
    response_model=PublicReceipt,
    summary="A decision receipt anyone can read",
    responses=problem_responses(404, 429),
)
async def get_receipt(
    run_id: UUID,
    request: Request,
    factory: SessionFactoryDep,
    principal: Annotated[Principal, Depends(get_optional_principal)],
) -> PublicReceipt:
    """Public by design, also in live mode: it needs no account.

    It holds public OpenStreetMap facts and the tool's own readings (lane, band, the fact panel,
    the rules that fired, coverage). It never holds a reviewer name, a session, a decision, a
    draft or the evidence text.
    """
    del principal  # the caller's identity is not used; the endpoint is the same for everyone
    config = get_config(request)
    wait = get_limiter(request.app).hit(
        f"receipt:ip:{client_ip(request, config)}", capacity=RECEIPT_PER_IP_MINUTE, window_s=60.0
    )
    if wait is not None:
        raise RateLimitedError(
            "Too many requests; try again shortly.", headers=retry_after_headers(wait)
        )
    async with session_scope(factory) as session:
        row = await RunsRepo(session).get_row(run_id)
        if row is None:
            raise NotFoundError("The receipt does not exist.")
        case = await CasesRepo(session).get(row.case_id)
        if case is None:
            raise NotFoundError("The receipt does not exist.")
        stored = await ConfigsRepo(session).get(row.config_version)
        receipt = public_receipt(
            row,
            case.changeset_id,
            stored.pack_id if stored else None,
            stored.calibration_id if stored else None,
        )
    if receipt is None:
        raise NotFoundError("The receipt does not exist.")
    return receipt

"""Decision history across cases, as JSON and as a CSV export."""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import Query, Response

from cso.api.db import SessionFactoryDep
from cso.api.mappers import decision_row, from_keyset, to_keyset
from cso.api.pagination import MAX_LIMIT, decode_cursor, encode_cursor
from cso.api.problems import problem_responses
from cso.api.routing import Admin, Viewer, make_router
from cso.api.schemas import DecisionListQuery, DecisionListResponse, DecisionRow
from cso.persistence.db import session_scope
from cso.persistence.repos import OutcomesRepo

router = make_router(tags=["decisions"])

EXPORT_MAX_ROWS = 10_000
CSV_COLUMNS = (
    "outcome_id",
    "case_id",
    "changeset_id",
    "disposition",
    "response_type",
    "lane_at_decision",
    "band_at_decision",
    "reviewer_display",
    "created_at",
    "config_version",
    "decider_model",
)
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> str:
    """Text for one CSV cell; a leading formula character is defused so it stays text."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_STARTS) else text


def _row_cells(row: DecisionRow) -> list[str]:
    data = row.model_dump(mode="json")
    return [csv_cell(data.get(column)) for column in CSV_COLUMNS]


@router.get(
    "/decisions",
    response_model=DecisionListResponse,
    summary="Outcome history across cases",
    responses=problem_responses(400),
)
async def list_decisions(
    query: Annotated[DecisionListQuery, Query()],
    factory: SessionFactoryDep,
    principal: Viewer,
) -> DecisionListResponse:
    """Newest first; filter by reviewer, disposition and a date range."""
    cursor = None if query.cursor is None else to_keyset(decode_cursor(query.cursor))
    async with session_scope(factory) as session:
        page = await OutcomesRepo(session).list_decisions(
            cursor,
            query.limit,
            reviewer=query.reviewer,
            disposition=query.disposition,
            created_from=query.from_,
            created_to=query.to,
        )
        items = [decision_row(record) for record in page.items]
    next_cursor = None if page.next_cursor is None else encode_cursor(from_keyset(page.next_cursor))
    return DecisionListResponse(items=items, next_cursor=next_cursor)


@router.get(
    "/decisions/export.csv",
    summary="CSV export of the outcome history",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "One row per recorded outcome"},
        **problem_responses(400, 401, 403),
    },
)
async def export_decisions(
    query: Annotated[DecisionListQuery, Query()],
    factory: SessionFactoryDep,
    principal: Admin,
) -> Response:
    """Admin only; the same filters as the JSON list, at most 10,000 rows."""
    cursor = None if query.cursor is None else to_keyset(decode_cursor(query.cursor))
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    written = 0
    async with session_scope(factory) as session:
        outcomes = OutcomesRepo(session)
        while written < EXPORT_MAX_ROWS:
            page = await outcomes.list_decisions(
                cursor,
                min(MAX_LIMIT, EXPORT_MAX_ROWS - written),
                reviewer=query.reviewer,
                disposition=query.disposition,
                created_from=query.from_,
                created_to=query.to,
            )
            for record in page.items:
                writer.writerow(_row_cells(decision_row(record)))
                written += 1
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="decisions.csv"'},
    )

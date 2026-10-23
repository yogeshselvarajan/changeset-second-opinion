"""RFC 9457 problem+json: model, domain errors, pure mapping helpers and handler registration."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"
TYPE_PREFIX = "urn:cso:problem:"
REQUEST_ID_HEADER = "X-Request-ID"

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_log = logging.getLogger(__name__)


class FieldError(BaseModel):
    """One validation failure: where, what, and a stable machine code (never the input value)."""

    model_config = ConfigDict(extra="forbid")

    loc: list[str | int]
    msg: str
    type: str


class Problem(BaseModel):
    """application/problem+json body. Extension members (for example `job_id`) are allowed."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str
    errors: list[FieldError] | None = None


# --------------------------------------------------------------------------- domain errors


class ApiError(Exception):
    """Base for errors that map to a problem response; subclasses fix status and code."""

    status: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(detail or self.code)
        self.detail = detail
        self.headers = dict(headers or {})
        self.extensions = extensions


class InvalidParameterError(ApiError):
    """A query parameter, cursor or header value is malformed (400)."""

    status = 400
    code = "bad_request"


class InvalidCursorError(InvalidParameterError):
    """The pagination cursor is malformed or was altered (400)."""

    code = "invalid_cursor"


class UnauthorizedError(ApiError):
    """No valid session for an endpoint that needs one (401)."""

    status = 401
    code = "unauthorized"


class ForbiddenError(ApiError):
    """The session role is too low for the endpoint (403)."""

    status = 403
    code = "forbidden"


class NotFoundError(ApiError):
    """The addressed resource does not exist (404)."""

    status = 404
    code = "not_found"


class ConflictError(ApiError):
    """The request conflicts with current state, for example a job already queued (409)."""

    status = 409
    code = "conflict"


class UnprocessableError(ApiError):
    """The body is well formed but refers to something that does not fit, such as a run id (422)."""

    status = 422
    code = "validation_error"


class FinalTextInvalidError(UnprocessableError):
    """The reviewer's edited comment breaks the drafting rules (422); carries `violations`."""

    code = "final_text_invalid"


class PreconditionFailedError(ApiError):
    """If-Match did not match the current version (412); pass `current=` with the live record."""

    status = 412
    code = "precondition_failed"


class PreconditionRequiredError(ApiError):
    """The request needs an If-Match header (428)."""

    status = 428
    code = "precondition_required"


class RateLimitedError(ApiError):
    """Too many requests (429); pass `headers={"Retry-After": "..."}`."""

    status = 429
    code = "rate_limited"


class UpstreamUnavailableError(ApiError):
    """An external source such as MapRoulette could not be reached (502)."""

    status = 502
    code = "upstream_unavailable"


class ServiceUnavailableError(ApiError):
    """A dependency of this service is not ready (503)."""

    status = 503
    code = "service_unavailable"


_CODE_BY_STATUS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    412: "precondition_failed",
    422: "validation_error",
    428: "precondition_required",
    429: "rate_limited",
    502: "upstream_unavailable",
    503: "service_unavailable",
}


def _title(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def problem_type(code: str) -> str:
    """Stable `type` URI for a problem code."""
    return f"{TYPE_PREFIX}{code}"


# --------------------------------------------------------------------------- pure mapping


def get_request_id(request: Request) -> str:
    """Request id from state, else a well-formed `X-Request-ID` header, else a fresh one."""
    existing = getattr(request.state, "request_id", None)
    if existing:
        return str(existing)
    header = request.headers.get(REQUEST_ID_HEADER)
    request_id = header if header and _SAFE_REQUEST_ID.fullmatch(header) else uuid.uuid4().hex
    request.state.request_id = request_id
    return request_id


def problem_from_api_error(exc: ApiError, *, request_id: str, instance: str | None) -> Problem:
    """Problem for a domain error; extension members from the error are carried through."""
    return Problem.model_validate(
        {
            "type": problem_type(exc.code),
            "title": _title(exc.status),
            "status": exc.status,
            "detail": exc.detail,
            "instance": instance,
            "request_id": request_id,
            **exc.extensions,
        }
    )


def problem_from_http_exception(
    exc: StarletteHTTPException, *, request_id: str, instance: str | None
) -> Problem:
    """Problem for a Starlette or FastAPI HTTPException (including 404 and 405 from routing)."""
    code = _CODE_BY_STATUS.get(exc.status_code, "http_error")
    detail = exc.detail if isinstance(exc.detail, str) else None
    return Problem(
        type=problem_type(code),
        title=_title(exc.status_code),
        status=exc.status_code,
        detail=detail,
        instance=instance,
        request_id=request_id,
    )


def validation_status(errors: Sequence[Mapping[str, Any]]) -> int:
    """Status for a request validation failure.

    Bad query values and a bad changeset id are 400 (contract: GET /cases, POST /cases); a
    malformed path id is 404 (no such resource); everything else is 422.
    """
    locs = [tuple(error.get("loc", ())) for error in errors]
    if any(loc[:1] == ("path",) for loc in locs):
        return 404
    if any(loc[:1] == ("query",) for loc in locs):
        return 400
    if any(loc[:2] == ("body", "changeset_id") for loc in locs):
        return 400
    return 422


def problem_from_validation_error(
    exc: RequestValidationError, *, request_id: str, instance: str | None
) -> Problem:
    """Problem listing each failure's location, message and code; input values are not echoed."""
    raw = exc.errors()
    status = validation_status(raw)
    code = "not_found" if status == 404 else "validation_error"
    errors = [
        FieldError(
            loc=[part if isinstance(part, int) else str(part) for part in error.get("loc", ())],
            msg=str(error.get("msg", "")),
            type=str(error.get("type", "")),
        )
        for error in raw
    ]
    detail = (
        "The addressed resource does not exist."
        if status == 404
        else "The request has invalid parameters."
    )
    return Problem(
        type=problem_type(code),
        title=_title(status),
        status=status,
        detail=detail,
        instance=instance,
        request_id=request_id,
        errors=None if status == 404 else errors,
    )


def problem_for_unhandled(*, request_id: str, instance: str | None) -> Problem:
    """Generic 500 problem; internals are logged, never returned."""
    return Problem(
        type=problem_type("internal_error"),
        title=_title(500),
        status=500,
        detail="The server could not complete the request.",
        instance=instance,
        request_id=request_id,
    )


def problem_response(problem: Problem, headers: Mapping[str, str] | None = None) -> JSONResponse:
    """JSON response with the problem media type and the request id header."""
    merged = {REQUEST_ID_HEADER: problem.request_id, **(headers or {})}
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=merged,
    )


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries so documented error statuses carry the Problem schema."""
    return {
        status: {
            "model": Problem,
            "description": _title(status),
            "content": {PROBLEM_MEDIA_TYPE: {}},
        }
        for status in statuses
    }


# --------------------------------------------------------------------------- handlers


def install_problem_handlers(app: FastAPI) -> None:
    """Route every error of the app through problem+json."""

    async def on_api_error(request: Request, exc: Exception) -> JSONResponse:
        error = cast(ApiError, exc)
        problem = problem_from_api_error(
            error, request_id=get_request_id(request), instance=request.url.path
        )
        return problem_response(problem, error.headers)

    async def on_http_exception(request: Request, exc: Exception) -> JSONResponse:
        error = cast(StarletteHTTPException, exc)
        problem = problem_from_http_exception(
            error, request_id=get_request_id(request), instance=request.url.path
        )
        return problem_response(problem, error.headers)

    async def on_validation_error(request: Request, exc: Exception) -> JSONResponse:
        error = cast(RequestValidationError, exc)
        problem = problem_from_validation_error(
            error, request_id=get_request_id(request), instance=request.url.path
        )
        return problem_response(problem)

    async def on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        _log.exception("unhandled error", extra={"path": request.url.path})
        problem = problem_for_unhandled(
            request_id=get_request_id(request), instance=request.url.path
        )
        return problem_response(problem)

    app.add_exception_handler(ApiError, on_api_error)
    app.add_exception_handler(StarletteHTTPException, on_http_exception)
    app.add_exception_handler(RequestValidationError, on_validation_error)
    app.add_exception_handler(Exception, on_unhandled)

"""problem+json: shape, status mapping, request ids and handler registration."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from cso.api.problems import (
    PROBLEM_MEDIA_TYPE,
    ApiError,
    ConflictError,
    ForbiddenError,
    InvalidCursorError,
    InvalidParameterError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
    Problem,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
    UpstreamUnavailableError,
    install_problem_handlers,
    problem_from_api_error,
    problem_responses,
    problem_type,
    validation_status,
)
from cso.api.schemas import CreateCaseRequest


def make_app() -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/not-found")
    async def not_found() -> None:
        raise NotFoundError("No such case.")

    @app.get("/conflict")
    async def conflict() -> None:
        raise ConflictError("An analysis is already queued.", job_id="job-1")

    @app.get("/stale")
    async def stale() -> None:
        raise PreconditionFailedError("Outcome changed.", current={"disposition": "agree"})

    @app.get("/rate")
    async def rate() -> None:
        raise RateLimitedError("Slow down.", headers={"Retry-After": "5"})

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals: db password")

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(418, "short and stout", headers={"X-Extra": "1"})

    @app.get("/query")
    async def query(limit: int) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/things/{thing_id}")
    async def thing(thing_id: UUID) -> dict[str, str]:
        return {"id": str(thing_id)}

    @app.post("/cases")
    async def create(body: CreateCaseRequest) -> dict[str, int]:
        return {"changeset_id": body.changeset_id}

    return app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c  # type: ignore[misc]


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, object]:
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    for field in ("type", "title", "status", "request_id"):
        assert body[field] not in (None, "")
    assert body["status"] == status
    assert body["type"] == problem_type(code)
    assert response.headers["x-request-id"] == body["request_id"]
    return body  # type: ignore[no-any-return]


async def test_domain_errors_map_to_problems(client: httpx.AsyncClient) -> None:
    body = assert_problem(await client.get("/not-found"), 404, "not_found")
    assert body["detail"] == "No such case."
    assert body["instance"] == "/not-found"
    assert body["title"] == "Not Found"

    body = assert_problem(await client.get("/conflict"), 409, "conflict")
    assert body["job_id"] == "job-1"  # extension member carried through

    body = assert_problem(await client.get("/stale"), 412, "precondition_failed")
    assert body["current"] == {"disposition": "agree"}

    response = await client.get("/rate")
    assert_problem(response, 429, "rate_limited")
    assert response.headers["retry-after"] == "5"


async def test_unhandled_error_is_generic(client: httpx.AsyncClient) -> None:
    response = await client.get("/boom")
    body = assert_problem(response, 500, "internal_error")
    assert "secret" not in response.text
    assert body["detail"] == "The server could not complete the request."


async def test_http_exception_and_routing_errors(client: httpx.AsyncClient) -> None:
    response = await client.get("/teapot")
    body = assert_problem(response, 418, "http_error")
    assert body["detail"] == "short and stout"
    assert response.headers["x-extra"] == "1"

    assert_problem(await client.get("/nowhere"), 404, "not_found")
    assert_problem(await client.delete("/not-found"), 405, "method_not_allowed")


async def test_query_validation_is_400_without_echoing_input(client: httpx.AsyncClient) -> None:
    response = await client.get("/query", params={"limit": "secret-token"})
    body = assert_problem(response, 400, "validation_error")
    errors = body["errors"]
    assert isinstance(errors, list)
    assert errors[0]["loc"] == ["query", "limit"]
    assert set(errors[0]) == {"loc", "msg", "type"}
    assert "secret-token" not in response.text


async def test_body_validation_statuses(client: httpx.AsyncClient) -> None:
    body = assert_problem(
        await client.post("/cases", json={"changeset_id": "abc"}), 400, "validation_error"
    )
    assert body["errors"][0]["loc"] == ["body", "changeset_id"]  # type: ignore[index]

    assert_problem(
        await client.post("/cases", json={"changeset_id": 5, "source": "email"}),
        422,
        "validation_error",
    )
    assert_problem(
        await client.post("/cases", json={"changeset_id": 5, "x": 1}), 422, "validation_error"
    )


async def test_malformed_path_id_is_404(client: httpx.AsyncClient) -> None:
    body = assert_problem(await client.get("/things/not-a-uuid"), 404, "not_found")
    assert "errors" not in body


async def test_request_id_header_is_honoured_or_replaced(client: httpx.AsyncClient) -> None:
    ok = await client.get("/not-found", headers={"X-Request-ID": "req-123.abc"})
    assert ok.json()["request_id"] == "req-123.abc"

    unsafe = await client.get("/not-found", headers={"X-Request-ID": "bad id\twith space"})
    rid = unsafe.json()["request_id"]
    assert rid != "bad id\twith space"
    assert len(rid) == 32

    too_long = await client.get("/not-found", headers={"X-Request-ID": "a" * 65})
    assert too_long.json()["request_id"] != "a" * 65


# --------------------------------------------------------------------------- pure helpers


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (InvalidParameterError("x"), 400, "bad_request"),
        (InvalidCursorError("x"), 400, "invalid_cursor"),
        (UnauthorizedError("x"), 401, "unauthorized"),
        (ForbiddenError("x"), 403, "forbidden"),
        (NotFoundError("x"), 404, "not_found"),
        (ConflictError("x"), 409, "conflict"),
        (PreconditionFailedError("x"), 412, "precondition_failed"),
        (PreconditionRequiredError("x"), 428, "precondition_required"),
        (RateLimitedError("x"), 429, "rate_limited"),
        (UpstreamUnavailableError("x"), 502, "upstream_unavailable"),
        (ServiceUnavailableError("x"), 503, "service_unavailable"),
    ],
)
def test_error_classes_map_to_status_and_code(error: ApiError, status: int, code: str) -> None:
    problem = problem_from_api_error(error, request_id="r1", instance="/x")
    assert (problem.status, problem.type) == (status, problem_type(code))
    assert problem.request_id == "r1"
    assert problem.instance == "/x"


def test_validation_status_rules() -> None:
    assert validation_status([{"loc": ("query", "limit")}]) == 400
    assert validation_status([{"loc": ("body", "changeset_id")}]) == 400
    assert validation_status([{"loc": ("body", "source")}]) == 422
    assert validation_status([{"loc": ("path", "id")}, {"loc": ("query", "q")}]) == 404
    assert validation_status([]) == 422


def test_problem_round_trip_and_documented_responses() -> None:
    problem = Problem(title="Not Found", status=404, request_id="r")
    assert problem.type == "about:blank"
    assert Problem.model_validate(problem.model_dump()) == problem

    docs = problem_responses(404, 409)
    assert set(docs) == {404, 409}
    assert docs[404]["model"] is Problem
    assert PROBLEM_MEDIA_TYPE in docs[404]["content"]

"""Request ids: accepted when sane, replaced when not, echoed, logged, present in problems."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from cso.api.problems import install_problem_handlers
from cso.api.security import install_security
from cso.observability import RequestContextMiddleware
from cso.observability.middleware import accept_request_id, route_template


class Typed(BaseModel):
    n: int


def build_app() -> FastAPI:
    """A tiny app in the production middleware order: security inside, request context outside."""
    app = FastAPI()
    install_problem_handlers(app)
    install_security(app)

    @app.get("/api/things/{thing_id}")
    async def thing(thing_id: int) -> dict[str, int]:
        return {"id": thing_id}

    @app.post("/api/things")
    async def create() -> dict[str, str]:
        return {"ok": "yes"}

    @app.put("/api/typed")
    async def typed(body: Typed) -> dict[str, int]:
        return {"n": body.n}

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.fixture
async def http():
    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_a_sane_inbound_id_is_echoed(http, logs) -> None:
    response = await http.get("/api/things/7", headers={"X-Request-ID": "client-req.42_A"})
    assert response.headers["x-request-id"] == "client-req.42_A"
    assert all(line["request_id"] == "client-req.42_A" for line in logs.events("http.request"))


@pytest.mark.parametrize(
    "bad", ["has space", "x" * 65, "semi;colon", "new\nline", "<script>", "emoji-☃", ""]
)
async def test_unsafe_inbound_ids_are_replaced_with_a_fresh_one(http, bad: str) -> None:
    try:
        response = await http.get("/api/things/1", headers={"X-Request-ID": bad})
    except (httpx.InvalidURL, ValueError, UnicodeError):
        pytest.skip("the client refuses to send this header value at all")
    echoed = response.headers["x-request-id"]
    assert echoed != bad and len(echoed) == 32 and echoed.isalnum()


async def test_each_request_without_an_id_gets_a_different_one(http) -> None:
    a = (await http.get("/api/things/1")).headers["x-request-id"]
    b = (await http.get("/api/things/1")).headers["x-request-id"]
    assert a != b


def test_accept_request_id_unit() -> None:
    assert accept_request_id("abc-123") == "abc-123"
    assert accept_request_id(None) != accept_request_id(None)
    assert len(accept_request_id("bad id")) == 32


async def test_problems_from_the_inner_security_layer_carry_the_same_request_id(http) -> None:
    """A mutation with a session cookie but no CSRF header is refused by SecurityMiddleware."""
    response = await http.post(
        "/api/things",
        headers={"X-Request-ID": "trace-me-1", "Cookie": "cso_session=anything"},
    )
    assert response.status_code == 403
    assert response.headers["x-request-id"] == "trace-me-1"
    assert response.json()["request_id"] == "trace-me-1"


async def test_validation_problems_carry_the_request_id_too(http) -> None:
    response = await http.put(
        "/api/typed", json={"n": "not a number"}, headers={"X-Request-ID": "r-422"}
    )
    assert response.status_code in {400, 422}
    assert response.headers["x-request-id"] == "r-422"
    assert response.json()["request_id"] == "r-422"


async def test_unhandled_errors_still_get_an_id_and_an_access_line(http, logs) -> None:
    response = await http.get("/api/boom", headers={"X-Request-ID": "r-500"})
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "r-500"
    (line,) = [e for e in logs.events("http.request") if e["request_id"] == "r-500"]
    assert line["status"] == 500


async def test_access_line_has_method_route_template_status_and_duration_only(http, logs) -> None:
    await http.get("/api/things/12345?secret=hunter2&code=cso-aaaaaaaa-bbbbbbbbbbbb")
    (line,) = logs.events("http.request")
    assert line["method"] == "GET" and line["status"] == 200
    assert line["route"] == "/api/things/{thing_id}"  # the template, not /api/things/12345
    assert isinstance(line["duration_ms"], float) and line["duration_ms"] >= 0
    assert "hunter2" not in logs.text and "12345" not in logs.text and "secret" not in logs.text
    assert "path" not in line and "query" not in line


async def test_unmatched_paths_are_logged_under_a_fixed_label(http, logs) -> None:
    await http.get("/api/definitely/not/here/9876")
    (line,) = logs.events("http.request")
    assert line["route"] == "unmatched" and line["status"] == 404
    assert "9876" not in logs.text


async def test_probe_paths_are_logged_at_debug_so_they_are_easy_to_filter(logs) -> None:
    app = build_app()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.middleware_stack = None  # rebuild so the late route is included
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/healthz")
    (line,) = logs.events("http.request")
    assert line["level"] == "debug"


class _Route:
    def __init__(self, path: str) -> None:
        self.path = path


def test_route_template_without_a_route_is_unmatched() -> None:
    assert route_template({}) == "unmatched"


def test_route_template_restores_the_included_router_prefix() -> None:
    scope = {
        "route": _Route("/cases/{id}"),
        "path": "/api/v1/cases/5d1c-77",
        "path_params": {"id": "5d1c-77"},
    }
    assert route_template(scope) == "/api/v1/cases/{id}"


def test_route_template_handles_routes_without_parameters_and_without_a_prefix() -> None:
    assert route_template({"route": _Route("/cases"), "path": "/api/v1/cases"}) == "/api/v1/cases"
    assert route_template({"route": _Route("/healthz"), "path": "/healthz"}) == "/healthz"


def test_route_template_handles_typed_and_multiple_parameters() -> None:
    scope = {
        "route": _Route("/cases/{id}/drafts/{n:int}"),
        "path": "/api/v1/cases/abc/drafts/3",
        "path_params": {"id": "abc", "n": 3},
    }
    assert route_template(scope) == "/api/v1/cases/{id}/drafts/{n:int}"


def test_route_template_falls_back_to_the_route_path_when_it_cannot_match() -> None:
    scope = {"route": _Route("/things/{id}"), "path": "/elsewhere", "path_params": {"id": "1"}}
    assert route_template(scope) == "/things/{id}"

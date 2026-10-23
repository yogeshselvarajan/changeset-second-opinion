"""Request-id and access-log middleware (outermost, so every response and problem carries an id).

Pure ASGI, like `SecurityMiddleware`. It accepts a well-formed inbound `X-Request-ID` or makes a
fresh one, stores it where `get_request_id` looks (`scope["state"]`), echoes it on the response,
binds it for every log line of the request, and writes one access line: method, route template,
status and duration. Query strings and bodies are never logged.
"""

from __future__ import annotations

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cso.observability.context import log_context
from cso.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS, METRICS

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Probes and scrapes are logged at debug level so they do not drown real traffic.
_QUIET_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})

log = structlog.get_logger("cso.access")


def new_request_id() -> str:
    """A fresh opaque request id."""
    return uuid.uuid4().hex


def accept_request_id(candidate: str | None) -> str:
    """The inbound id if it is short and url-safe, else a new one (never trust header content)."""
    if candidate and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return new_request_id()


_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}")


def route_template(scope: Scope) -> str:
    """The matched route's full path template (`/api/v1/cases/{id}`), never the raw path.

    The route object only knows its path relative to the router it was declared on, and how an
    included router's prefix is stored differs between Starlette and FastAPI versions. So the
    prefix is recovered from public data instead: it is whatever the actual request path has in
    front of the route's own path once the route's parameters are filled in from `path_params`.
    """
    route = scope.get("route")
    relative = getattr(route, "path", None)
    if not relative:
        return "unmatched"
    params = scope.get("path_params") or {}
    own = _PARAM.sub(lambda m: str(params.get(m.group(1), m.group(0))), str(relative))
    actual = str(scope.get("path", ""))
    if own and actual.endswith(own):
        return actual[: len(actual) - len(own)] + str(relative)
    return str(relative)


class RequestContextMiddleware:
    """Assign, echo and bind the request id, count the request and write the access line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inbound = next(
            (v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-request-id"),
            None,
        )
        request_id = accept_request_id(inbound)
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers", []))
                if not any(k.lower() == b"x-request-id" for k, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000
                route = route_template(scope)
                method = str(scope["method"])
                METRICS.inc(HTTP_REQUESTS, method=method, route=route, status=status)
                METRICS.observe(HTTP_LATENCY, elapsed_ms, route=route)
                emit = log.debug if scope["path"] in _QUIET_PATHS else log.info
                emit(
                    "http.request",
                    method=method,
                    route=route,
                    status=status,
                    duration_ms=round(elapsed_ms, 1),
                )

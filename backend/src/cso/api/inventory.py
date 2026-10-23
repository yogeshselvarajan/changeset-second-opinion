"""Endpoint inventory of the v1 API, for tests of the routers that come later.

Paths are relative to `/api/v1`, except `ROOT_PATHS`, which stay at the application root
(`/healthz` is used by the container health check). Path parameters are all written `{id}` as in
the contract; compare routes with `route_key`, which ignores parameter names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cso.api.deps import Role

API_PREFIX = "/api/v1"
ROOT_PATHS = frozenset({"/healthz", "/readyz", "/site.webmanifest"})


@dataclass(frozen=True)
class Endpoint:
    """One row of the contract's endpoint table."""

    method: str
    path: str
    role: Role | None  # None: no authentication needed
    success: tuple[int, ...]
    errors: tuple[int, ...] = ()

    @property
    def full_path(self) -> str:
        """Path as mounted on the application."""
        return self.path if self.path in ROOT_PATHS else f"{API_PREFIX}{self.path}"


_V, _R, _A = Role.VIEWER, Role.REVIEWER, Role.ADMIN

INVENTORY: tuple[Endpoint, ...] = (
    Endpoint("GET", "/healthz", None, (200,)),
    Endpoint("GET", "/readyz", None, (200,), (503,)),
    Endpoint("POST", "/auth/login", None, (200,), (401,)),
    Endpoint("POST", "/auth/logout", _V, (204,)),
    Endpoint("GET", "/auth/osm/start", None, (302,), (404,)),
    Endpoint("GET", "/auth/osm/callback", None, (302,), (404,)),
    Endpoint("GET", "/me", None, (200,)),
    Endpoint("GET", "/cases", _V, (200,), (400,)),
    Endpoint("POST", "/cases", _R, (201, 200), (400, 429)),
    Endpoint("POST", "/cases/import", _R, (202,), (400, 502)),
    Endpoint("GET", "/cases/{id}", _V, (200,), (404,)),
    Endpoint("GET", "/cases/{id}/evidence", _V, (200,), (404,)),
    Endpoint("GET", "/cases/{id}/runs", _V, (200,), (404,)),
    Endpoint("GET", "/runs/{id}", _V, (200,), (404,)),
    Endpoint("GET", "/receipts/{id}", None, (200,), (404, 429)),
    Endpoint("POST", "/cases/{id}/analyses", _R, (202, 200), (404, 409, 429)),
    Endpoint("GET", "/jobs/{id}", _V, (200,), (404,)),
    Endpoint("POST", "/jobs/{id}/cancel", _R, (202,), (404, 409)),
    Endpoint("POST", "/cases/{id}/drafts", _R, (202,), (404, 409, 429)),
    Endpoint("GET", "/drafts/{id}", _V, (200,), (404,)),
    Endpoint("PUT", "/cases/{id}/outcome", _R, (200,), (404, 412, 422, 428)),
    Endpoint("GET", "/cases/{id}/audit", _V, (200,), (404,)),
    Endpoint("GET", "/decisions", _V, (200,)),
    Endpoint("GET", "/decisions/export.csv", _A, (200,), (403,)),
    Endpoint("GET", "/config", _V, (200,)),
    Endpoint("GET", "/config/versions", _A, (200,), (403,)),
    Endpoint("GET", "/config/packs", _V, (200,), (409,)),
    Endpoint("POST", "/config/packs/{id}/activate", _A, (200,), (403, 404, 409)),
    Endpoint("GET", "/config/diff", _V, (200,), (404, 409)),
    Endpoint("GET", "/config/reliability", _A, (200,), (403, 404)),
    Endpoint("POST", "/config/calibrate", _A, (200,), (403, 404)),
    Endpoint("POST", "/workspace/claim", _R, (200,), (403, 409)),
    Endpoint("GET", "/settings", _A, (200,), (403,)),
    Endpoint("PUT", "/settings", _A, (200,), (403, 412, 422, 428)),
    Endpoint("GET", "/site.webmanifest", None, (200,)),
    Endpoint("GET", "/public/branding", None, (200,)),
    Endpoint("GET", "/public/branding/logo.svg", None, (200,), (404,)),
    Endpoint("GET", "/invites", _A, (200,), (403,)),
    Endpoint("POST", "/invites", _A, (201,), (403, 422)),
    Endpoint("POST", "/invites/{id}/revoke", _A, (200,), (403, 404)),
)

_PARAM = re.compile(r"\{[^/}]+\}")


def route_key(method: str, path: str) -> tuple[str, str]:
    """Comparable key for a route: upper-case method, `/api/v1` removed, parameters as `{}`."""
    relative = path.removeprefix(API_PREFIX) or "/"
    return method.upper(), _PARAM.sub("{}", relative)


def inventory_keys() -> frozenset[tuple[str, str]]:
    """`route_key` of every inventory row."""
    return frozenset(route_key(e.method, e.path) for e in INVENTORY)

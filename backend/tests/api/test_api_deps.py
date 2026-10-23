"""Role ordering and the require_role placeholder dependency."""

from __future__ import annotations

import httpx
import pytest
from fastapi import Depends, FastAPI

from cso.api.deps import (
    ANONYMOUS_VIEWER,
    Principal,
    Role,
    check_role,
    get_principal,
    has_role,
    require_role,
)
from cso.api.problems import ForbiddenError, UnauthorizedError, install_problem_handlers

REVIEWER = Principal(id="u1", display_name="mapper_a", role=Role.REVIEWER)
ADMIN = Principal(id="u2", display_name="mapper_b", role=Role.ADMIN)
VIEWER_SESSION = Principal(id="u3", display_name="mapper_c", role=Role.VIEWER)


def test_role_ordering() -> None:
    assert has_role(ADMIN, Role.REVIEWER) and has_role(ADMIN, Role.VIEWER)
    assert has_role(REVIEWER, Role.VIEWER) and not has_role(REVIEWER, Role.ADMIN)
    assert has_role(ANONYMOUS_VIEWER, Role.VIEWER) and not has_role(ANONYMOUS_VIEWER, Role.REVIEWER)


def test_check_role_distinguishes_401_and_403() -> None:
    assert check_role(REVIEWER, Role.REVIEWER) is REVIEWER
    with pytest.raises(UnauthorizedError):
        check_role(ANONYMOUS_VIEWER, Role.REVIEWER)
    with pytest.raises(ForbiddenError):
        check_role(VIEWER_SESSION, Role.REVIEWER)
    with pytest.raises(ForbiddenError):
        check_role(REVIEWER, Role.ADMIN)


async def test_placeholder_principal_is_anonymous_viewer() -> None:
    principal = await get_principal()
    assert principal.anonymous
    assert principal.role is Role.VIEWER


def make_app() -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/read")
    async def read(p: Principal = Depends(require_role(Role.VIEWER))) -> dict[str, str]:  # noqa: B008
        return {"role": p.role.value}

    @app.post("/write")
    async def write(p: Principal = Depends(require_role(Role.REVIEWER))) -> dict[str, str]:  # noqa: B008
        return {"role": p.role.value}

    @app.get("/export")
    async def export(p: Principal = Depends(require_role(Role.ADMIN))) -> dict[str, str]:  # noqa: B008
        return {"role": p.role.value}

    return app


async def test_require_role_over_http() -> None:
    app = make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/read")).status_code == 200
        denied = await client.post("/write")
        assert denied.status_code == 401
        assert denied.headers["content-type"].startswith("application/problem+json")

        app.dependency_overrides[get_principal] = lambda: REVIEWER
        assert (await client.post("/write")).status_code == 200
        assert (await client.get("/export")).status_code == 403

        app.dependency_overrides[get_principal] = lambda: ADMIN
        assert (await client.get("/export")).status_code == 200

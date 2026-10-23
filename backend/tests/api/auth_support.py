"""Helpers for the auth tests: a tiny app with the real auth wiring and a throwaway database.

The app has the auth router, the security middleware and a handful of routes that stand in for
the other routers, so these tests do not depend on them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cso.api.auth import router as auth_router
from cso.api.auth_core import AuthConfig, InviteHasher, create_invite
from cso.api.auth_osm import router as osm_router
from cso.api.deps import Principal, Role, require_role
from cso.api.problems import install_problem_handlers
from cso.api.security import RateLimiter, analysis_quota, install_security
from cso.api.v1.workspace import router as workspace_router
from cso.persistence.db import make_engine, make_sessionmaker, session_scope
from cso.persistence.tables import Base

# Cheap argon2 so the suite stays fast; the algorithm and code paths are the real ones.
CHEAP: dict[str, Any] = {
    "argon2_time_cost": 1,
    "argon2_memory_cost_kib": 8,
    "argon2_parallelism": 1,
}


def make_config(**overrides: Any) -> AuthConfig:
    """An AuthConfig with cheap hashing; pass any field to override."""
    return AuthConfig(**{**CHEAP, **overrides})


@dataclass
class Env:
    """Everything a test needs: the app, its database and the pieces wired into it."""

    app: FastAPI
    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]
    config: AuthConfig
    limiter: RateLimiter
    hasher: InviteHasher


def build_app(config: AuthConfig, limiter: RateLimiter) -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)
    install_security(app, config=config, limiter=limiter)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(osm_router, prefix="/api/v1")
    app.include_router(workspace_router, prefix="/api/v1")  # for POST /workspace/claim

    @app.get("/api/v1/ping")
    async def ping(p: Principal = Depends(require_role(Role.VIEWER))) -> dict[str, str]:  # noqa: B008
        return {"role": p.role.value}

    @app.post("/api/v1/write")
    async def write(p: Principal = Depends(require_role(Role.REVIEWER))) -> dict[str, str | None]:  # noqa: B008
        return {"by": p.display_name, "id": p.id}

    @app.get("/api/v1/admin")
    async def admin_read(p: Principal = Depends(require_role(Role.ADMIN))) -> dict[str, str]:  # noqa: B008
        return {"role": p.role.value}

    @app.post("/api/v1/admin")
    async def admin_write(p: Principal = Depends(require_role(Role.ADMIN))) -> dict[str, str]:  # noqa: B008
        return {"role": p.role.value}

    @app.post("/api/v1/open")
    async def open_post() -> dict[str, bool]:
        """A mutating route with no principal dependency: only the middleware guards it."""
        return {"ok": True}

    @app.post("/api/v1/analyze", dependencies=[Depends(analysis_quota)])
    async def analyze(p: Principal = Depends(require_role(Role.REVIEWER))) -> dict[str, bool]:  # noqa: B008
        return {"queued": True}

    @app.post("/api/v1/analyze-anon", dependencies=[Depends(analysis_quota)])
    async def analyze_anon() -> dict[str, bool]:
        return {"queued": True}

    return app


@asynccontextmanager
async def build_env(tmp_path: Path, **overrides: Any) -> AsyncIterator[Env]:
    """A fresh database and app; disposes the engine on exit."""
    config = make_config(**overrides)
    limiter = RateLimiter()
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = make_sessionmaker(engine)
    app = build_app(config, limiter)
    app.state.session_factory = factory
    try:
        yield Env(app, engine, factory, config, limiter, InviteHasher(config))
    finally:
        await engine.dispose()


def client_for(env: Env, base_url: str = "http://testserver") -> httpx.AsyncClient:
    """An httpx client talking straight to the app (no network)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url=base_url)


async def mint_invite(
    env: Env,
    role: str = "reviewer",
    *,
    max_uses: int | None = None,
    ttl: timedelta | None = None,
    label: str = "test",
) -> str:
    """Create an invite code in the test database and return its plaintext."""
    async with session_scope(env.factory) as db:
        code, _ = await create_invite(
            db, env.hasher, role=role, label=label, max_uses=max_uses, ttl=ttl
        )
    return code


async def login_as(client: httpx.AsyncClient, code: str, name: str = "mapper_a") -> httpx.Response:
    """POST /auth/login; the client's cookie jar keeps the session cookies."""
    return await client.post("/api/v1/auth/login", json={"invite_code": code, "display_name": name})


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    """The X-CSRF header a logged-in SPA would send (the value of the readable cookie)."""
    token = client.cookies.get("cso_csrf")
    assert token, "not logged in"
    return {"X-CSRF": token}


async def sql(env: Env, statement: str, **params: Any) -> list[Any]:
    """Run a raw statement against the test database and return all rows (for assertions)."""
    async with env.engine.begin() as conn:
        result = await conn.execute(sa.text(statement), params)
        return list(result.fetchall()) if result.returns_rows else []

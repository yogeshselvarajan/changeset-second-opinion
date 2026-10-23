"""Router test fixtures: a fresh SQLite database and an app whose caller can be switched."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from api_support import REVIEWER, Caller
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cso.api.deps import get_principal
from cso.main import create_app
from cso.observability.readiness import head_revision
from cso.persistence.db import make_engine, make_sessionmaker
from cso.persistence.tables import Base


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Look migrated: /readyz also checks that the stored revision is the code's head.
        await conn.execute(
            sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        await conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": head_revision()}
        )
    yield eng
    await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest.fixture
def caller() -> Caller:
    return Caller(REVIEWER)


@pytest.fixture
def app(factory: async_sessionmaker[AsyncSession], caller: Caller) -> FastAPI:
    application = create_app()
    application.state.session_factory = factory
    application.dependency_overrides[get_principal] = lambda: caller.principal
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

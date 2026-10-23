"""Observability test fixtures: a migrated-looking database, captured logs, an API client."""

from __future__ import annotations

import io
import json
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# The jobs tests already have scripted fakes (Decider, clock, replay providers); reuse them.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "jobs"))

from cso.api.deps import Principal, Role, get_principal  # noqa: E402
from cso.main import create_app  # noqa: E402
from cso.observability import logging as obs_logging  # noqa: E402
from cso.observability.metrics import METRICS  # noqa: E402
from cso.observability.readiness import head_revision  # noqa: E402
from cso.persistence.db import make_engine, make_sessionmaker  # noqa: E402
from cso.persistence.tables import Base  # noqa: E402

REVIEWER = Principal(id="reviewer-rae", display_name="Rae Reviewer", role=Role.REVIEWER)


async def migrate_stamp(engine: AsyncEngine, revision: str | None) -> None:
    """Record `revision` as the stored migration (None leaves the table out)."""
    async with engine.begin() as conn:
        if revision is None:
            return
        await conn.execute(
            sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        await conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": revision}
        )


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'obs.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate_stamp(eng, head_revision())
    yield eng
    await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest.fixture(autouse=True)
def clean_metrics() -> Iterator[None]:
    METRICS.reset()
    yield
    METRICS.reset()


class Logs:
    """Everything logged since the fixture started, parsed from the JSON lines."""

    def __init__(self, stream: io.StringIO) -> None:
        self._stream = stream

    @property
    def text(self) -> str:
        return self._stream.getvalue()

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.text.splitlines() if line.strip()]

    def events(self, name: str) -> list[dict[str, Any]]:
        return [line for line in self.lines() if line.get("event") == name]


@pytest.fixture
def logs() -> Iterator[Logs]:
    stream = io.StringIO()
    obs_logging.configure_logging(fmt="json", level="DEBUG", stream=stream, force=True)
    yield Logs(stream)
    structlog.reset_defaults()
    obs_logging._configured = None


@pytest.fixture
def app(factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    application = create_app()
    application.state.session_factory = factory
    application.dependency_overrides[get_principal] = lambda: REVIEWER
    return application


@pytest.fixture
def make_client() -> Callable[..., httpx.AsyncClient]:
    def build(app: FastAPI, *, client: tuple[str, int] = ("127.0.0.1", 123)) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, client=client)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return build


@pytest.fixture
async def client(
    app: FastAPI, make_client: Callable[..., httpx.AsyncClient]
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as http:
        yield http

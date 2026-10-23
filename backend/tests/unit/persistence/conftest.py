"""Fixtures: a fresh SQLite database per test, created straight from the metadata.

Migrations are exercised separately in tests/integration/test_migrations.py; building the schema
with `create_all` keeps the repository tests fast.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from persistence_support import CASE_01, CASE_02, rendered_snapshot
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cso.domain.models import EvidenceSnapshot
from cso.persistence.db import make_engine, make_sessionmaker
from cso.persistence.tables import Base


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    eng = make_engine(url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest.fixture(scope="session")
async def snapshot_01() -> EvidenceSnapshot:
    return await rendered_snapshot(CASE_01)  # frozen model: safe to share across tests


@pytest.fixture(scope="session")
async def snapshot_02() -> EvidenceSnapshot:
    return await rendered_snapshot(CASE_02)

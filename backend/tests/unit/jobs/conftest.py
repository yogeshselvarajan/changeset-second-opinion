"""Fixtures: a fresh SQLite database per test and a worker builder on fakes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from jobs_support import FakePanelDecider, ManualClock, config, make_deps
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cso.jobs import Deps, Worker
from cso.persistence.db import make_engine, make_sessionmaker
from cso.persistence.tables import Base


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def decider() -> FakePanelDecider:
    return FakePanelDecider(config()[0])


@pytest.fixture
def deps(decider: FakePanelDecider) -> Deps:
    return make_deps(decider)


@pytest.fixture
def make_worker(
    factory: async_sessionmaker[AsyncSession], deps: Deps, clock: ManualClock
) -> Callable[..., Worker]:
    """Build a Worker on the fake clock; keyword overrides go to the Worker (deps= swaps deps)."""

    def build(**overrides: Any) -> Worker:
        options: dict[str, Any] = {
            "clock": clock,
            "poll_interval_s": 0.01,
            "reaper_interval_s": 0.05,
            "rng": lambda: 0.5,
            "concurrency": 2,
        }
        use_deps = overrides.pop("deps", deps)
        options.update(overrides)
        return Worker(factory, use_deps, **options)

    return build

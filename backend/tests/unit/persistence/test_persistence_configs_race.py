"""`ConfigsRepo.add_if_absent` is safe when several sessions store the same version at once.

The race is timing dependent, so the tests force the interleaving: the first `get` of the config
row in each session waits on a barrier until every session has seen the version as absent, which
makes all of them go on to insert. Before the fix this raised `IntegrityError` on the primary key.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import sqlalchemy as sa
from persistence_support import config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.persistence.db import session_scope
from cso.persistence.repos import ConfigsRepo
from cso.persistence.repos._common import utcnow
from cso.persistence.tables import CommunityConfigRow

SESSIONS = 4


def _hold_first_lookups_at_barrier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make each session's first config lookup wait until all sessions have looked."""
    barrier = asyncio.Barrier(SESSIONS)
    original = AsyncSession.get
    seen: set[int] = set()

    async def get(self: AsyncSession, entity: Any, ident: Any, **kw: Any) -> Any:
        found = await original(self, entity, ident, **kw)
        if entity is CommunityConfigRow and id(self) not in seen:
            seen.add(id(self))
            await barrier.wait()
        return found

    monkeypatch.setattr(AsyncSession, "get", get)


async def _store(
    factory: async_sessionmaker[AsyncSession], *, activate: bool, yaml_text: str
) -> CommunityConfigRow:
    cfg, _ = config()
    async with session_scope(factory) as session:
        return await ConfigsRepo(session).add_if_absent(cfg, yaml_text, activate=activate)


async def test_concurrent_add_if_absent_stores_one_row(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, yaml_text = config()
    _hold_first_lookups_at_barrier(monkeypatch)

    rows = await asyncio.gather(
        *[_store(factory, activate=False, yaml_text=yaml_text) for _ in range(SESSIONS)]
    )

    assert {row.version for row in rows} == {config()[0].version}
    async with factory() as session:
        stored = (await session.execute(sa.select(CommunityConfigRow))).scalars().all()
    assert len(stored) == 1
    assert stored[0].yaml == yaml_text and stored[0].is_active is False


async def test_concurrent_add_if_absent_with_activate_leaves_it_active(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, yaml_text = config()
    _hold_first_lookups_at_barrier(monkeypatch)

    await asyncio.gather(
        *[_store(factory, activate=True, yaml_text=yaml_text) for _ in range(SESSIONS)]
    )

    async with factory() as session:
        repo = ConfigsRepo(session)
        stored = await repo.list_versions()
        active = await repo.get_active()
    assert len(stored) == 1
    assert active is not None and active.version == cfg.version


async def test_losing_the_race_never_overwrites_the_stored_yaml(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    cfg, yaml_text = config()
    await _store(factory, activate=False, yaml_text=yaml_text)

    # A second writer arrives with a different text for the same version (cannot happen for a
    # content hash, but the stored row is immutable either way).
    async with session_scope(factory) as session:
        repo = ConfigsRepo(session)
        await repo._insert_ignoring_conflict(
            {
                "version": cfg.version,
                "yaml": "other: text",
                "created_at": utcnow(),
                "is_active": True,
                "pack_id": None,
                "calibration_id": None,
            }
        )

    async with factory() as session:
        row = await ConfigsRepo(session).get(cfg.version)
    assert row is not None and row.yaml == yaml_text and row.is_active is False

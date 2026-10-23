"""The worker decides with the configuration an admin activated, and a restart keeps it."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.config import CommunityConfig, default_config_path
from cso.jobs import Deps, Worker
from cso.persistence.db import session_scope
from cso.persistence.repos import ConfigsRepo


def _strict() -> tuple[CommunityConfig, str]:
    path = default_config_path().parent / "strict-review.yaml"
    text = path.read_text(encoding="utf-8")
    return CommunityConfig.from_yaml_text(text), text


async def test_without_an_activation_the_worker_uses_the_config_it_started_with(
    make_worker: Callable[..., Worker], deps: Deps
) -> None:
    worker = make_worker()
    await worker.ensure_config()
    assert (await worker.active_config()).version == deps.config.version


async def test_an_activated_pack_is_used_by_the_next_job(
    make_worker: Callable[..., Worker], factory: async_sessionmaker[AsyncSession], deps: Deps
) -> None:
    worker = make_worker()
    await worker.ensure_config()
    strict, text = _strict()
    async with session_scope(factory) as session:
        await ConfigsRepo(session).add_if_absent(strict, text, activate=True)
    chosen = await worker.active_config()
    assert chosen.version == strict.version and chosen.pack_id == "strict-review"
    assert chosen.version != deps.config.version


async def test_a_restart_keeps_the_pack_an_admin_chose(
    make_worker: Callable[..., Worker], factory: async_sessionmaker[AsyncSession]
) -> None:
    first = make_worker()
    await first.ensure_config()
    strict, text = _strict()
    async with session_scope(factory) as session:
        await ConfigsRepo(session).add_if_absent(strict, text, activate=True)
    second = make_worker()  # a restart: a new worker started with the default config again
    await second.ensure_config()
    async with session_scope(factory) as session:
        active = await ConfigsRepo(session).get_active()
    assert active is not None and active.version == strict.version
    assert (await second.active_config()).version == strict.version


async def test_an_unreadable_stored_config_falls_back_to_the_started_with_one(
    make_worker: Callable[..., Worker], factory: async_sessionmaker[AsyncSession], deps: Deps
) -> None:
    worker = make_worker()
    await worker.ensure_config()
    strict, _ = _strict()
    async with session_scope(factory) as session:
        await ConfigsRepo(session).add_if_absent(strict, "not: [valid", activate=True)
    assert (await worker.active_config()).version == deps.config.version

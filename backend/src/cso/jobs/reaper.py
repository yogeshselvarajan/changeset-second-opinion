"""Lease reaper: running jobs with an expired lease go back to the queue, or fail.

This is what makes jobs survive a crashed or restarted process: a worker that dies leaves its job
`running` with a lease; once the lease runs out any process's reaper re-queues it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import anyio
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.jobs.states import REAPER_INTERVAL_S
from cso.persistence.db import session_scope
from cso.persistence.repos import JobsRepo
from cso.persistence.repos.jobs_repo import ReapResult
from cso.persistence.tables import utcnow


async def reap_once(
    factory: async_sessionmaker[AsyncSession],
    *,
    clock: Callable[[], datetime] = utcnow,
    log: Any = None,
) -> ReapResult:
    """One pass: re-queue expired leases, fail those out of attempts. Safe to run in parallel."""
    logger = log or structlog.get_logger()
    async with session_scope(factory) as session:
        result = await JobsRepo(session).requeue_expired(now=clock())
    if result.requeued or result.failed:
        logger.warning("jobs.reaped", requeued=result.requeued, failed=result.failed)
    return result


async def reaper_loop(
    factory: async_sessionmaker[AsyncSession],
    *,
    interval_s: float = REAPER_INTERVAL_S,
    clock: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    log: Any = None,
    stop: anyio.Event | None = None,
) -> None:
    """Run `reap_once` every `interval_s` seconds until `stop` is set or the task is cancelled.

    Prefer `stop`: it lets a pass in progress finish, whereas cancelling in the middle of a query
    leaves the database connection half-closed. A failed pass is logged and retried next interval.
    """
    logger = log or structlog.get_logger()
    while stop is None or not stop.is_set():
        try:
            await reap_once(factory, clock=clock, log=logger)
        except Exception:
            logger.exception("jobs.reaper_failed")
        if stop is None:
            await sleep(interval_s)
        else:
            with anyio.move_on_after(interval_s):
                await stop.wait()

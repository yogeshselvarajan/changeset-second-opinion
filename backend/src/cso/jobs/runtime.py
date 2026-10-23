"""Start the worker: standalone (`cso worker`) or inside the API process (lifespan).

Both build the same `Worker`; the API process only does so when `CSO_JOBS_WORKER_ENABLED` is true
and the database is migrated. The compose `worker` service runs `cso worker` instead, with the API
started with `CSO_JOBS_WORKER_ENABLED=false`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from cso.jobs.deps import Deps, ReplayOsmProvider, build_deps
from cso.jobs.enqueue import enqueue_changeset
from cso.jobs.states import POLL_INTERVAL_S
from cso.jobs.worker import Worker
from cso.persistence.db import make_engine, make_sessionmaker, session_scope
from cso.persistence.repos import RunsRepo
from cso.settings import Settings

log = structlog.get_logger()


async def schema_ready(engine: AsyncEngine) -> bool:
    """True when the migrated `jobs` table exists."""
    async with engine.connect() as conn:
        return bool(await conn.run_sync(lambda c: sa.inspect(c).has_table("jobs")))


async def close_deps(deps: Deps) -> None:
    """Close the OSM provider and the Decider client if they hold connections."""
    await deps.osm.aclose()
    aclose = getattr(deps.decider, "aclose", None)
    if aclose is not None:
        await aclose()


async def run_worker_cli(
    settings: Settings,
    *,
    once: bool = False,
    fixture: str | None = None,
    concurrency: int = 2,
    fixtures_dir: Path | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """`cso worker`: loop forever, or with `--once` drain due jobs; `--fixture` enqueues one first.

    `--fixture NAME` is the replay demo: it applies migrations if the database is empty, creates
    the case of that fixture, enqueues its analysis, runs it, and prints the run.
    """
    from cso.persistence.admin import upgrade_database

    engine = make_engine(settings.database_url)
    deps: Deps | None = None
    try:
        if fixture and not await schema_ready(engine):
            await anyio.to_thread.run_sync(upgrade_database, settings.database_url)
        elif not await schema_ready(engine):
            out("database is not migrated; run `cso db upgrade` first")
            return 1
        deps = build_deps(settings, fixtures_dir=fixtures_dir)
        factory = make_sessionmaker(engine)
        worker = Worker(factory, deps, concurrency=concurrency)

        if fixture:
            if not isinstance(deps.osm, ReplayOsmProvider):
                out("--fixture needs CSO_MODE=replay")
                return 2
            changeset_id = deps.osm.changeset_id_of(fixture)
            async with session_scope(factory) as session:
                queued = await enqueue_changeset(session, changeset_id, actor="cli")
            outcomes = await worker.run_until_idle()
            for outcome in outcomes:
                out(f"job {outcome.job_id} {outcome.status.value} error={outcome.error}")
                await _print_run(factory, outcome.result_ref, out)
            if not outcomes:
                out(f"job {queued.job.id} was not due (status {queued.job.status})")
            return 0 if outcomes and outcomes[-1].error is None else 1
        if once:
            single = await worker.run_once()
            out("no due job" if single is None else f"job {single.job_id} {single.status.value}")
            return 0
        await worker.run_forever()
        return 0
    finally:
        if deps is not None:
            await close_deps(deps)
        await engine.dispose()


async def _print_run(
    factory: Any, result_ref: dict[str, Any] | None, out: Callable[[str], None]
) -> None:
    from uuid import UUID

    run_id = (result_ref or {}).get("run_id")
    if not run_id:
        return
    async with session_scope(factory) as session:
        row = await RunsRepo(session).get_row(UUID(str(run_id)))
    if row is None:
        return
    out(
        f"run {row.id} status={row.status} lane={row.lane} band={row.band} "
        f"nature={row.nature} response={row.response} failure={row.failure_reason}"
    )
    timing = (row.receipt or {}).get("timing_ms")
    out(f"timing_ms={timing}")


class EmbeddedWorker:
    """The worker inside the API process; start from the lifespan, stop on shutdown."""

    def __init__(self, settings: Settings, *, poll_interval_s: float = POLL_INTERVAL_S) -> None:
        self._settings = settings
        self._poll_interval_s = poll_interval_s
        self._engine: AsyncEngine | None = None
        self._deps: Deps | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event: anyio.Event | None = None

    async def start(self) -> bool:
        """Start polling; False (with a warning) when the database is not migrated."""
        engine = make_engine(self._settings.database_url)
        if not await schema_ready(engine):
            log.warning("jobs.worker_not_started", reason="run `cso db upgrade` first")
            await engine.dispose()
            return False
        self._engine = engine
        self._deps = build_deps(self._settings)
        worker = Worker(
            make_sessionmaker(engine), self._deps, poll_interval_s=self._poll_interval_s
        )
        self._stop_event = anyio.Event()
        self._task = asyncio.create_task(worker.run_forever(self._stop_event), name="cso-worker")
        log.info("jobs.worker_started", worker=worker.worker_id)
        return True

    async def stop(self, timeout_s: float = 10.0) -> None:
        """Stop claiming, give running jobs `timeout_s` to finish, then cancel (leases cover it)."""
        task, self._task = self._task, None
        if task is not None:
            if self._stop_event is not None:
                self._stop_event.set()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout_s)
            except TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if self._deps is not None:
            await close_deps(self._deps)
            self._deps = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

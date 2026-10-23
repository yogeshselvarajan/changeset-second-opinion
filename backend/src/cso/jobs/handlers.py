"""Job context and the handler registry (the draft handler lives in `draft_handler`).

A handler does one job kind end to end. It reports progress and cancellation points through
`JobContext.checkpoint`, and it finishes the job itself inside its final transaction (so a run and
the job's terminal state commit together). A handler that returns without finishing the job counts
as success.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.config import CommunityConfig
from cso.domain.enums import JobKind, JobStatus
from cso.jobs.deps import Deps
from cso.jobs.errors import JobCancelled, LeaseLost, PermanentJobError
from cso.jobs.states import LEASE_SECONDS
from cso.persistence.db import session_scope
from cso.persistence.repos import JobsRepo


@dataclass
class JobContext:
    """One claimed job as seen by its handler."""

    job_id: UUID
    case_id: UUID
    kind: JobKind
    attempts: int
    max_attempts: int
    response_type: str | None
    run_id: UUID | None
    worker_id: str
    factory: async_sessionmaker[AsyncSession]
    deps: Deps
    clock: Callable[[], datetime]
    log: Any
    lease_seconds: int = LEASE_SECONDS
    progress: dict[str, Any] | None = None  # what an earlier attempt saved (e.g. snapshot_id)
    # The configuration active when the job started (an admin may switch packs while the worker
    # runs); None means the one the worker was started with.
    config: CommunityConfig | None = None

    @property
    def active_config(self) -> CommunityConfig:
        """The community configuration this job decides and drafts with."""
        return self.config if self.config is not None else self.deps.config

    @property
    def last_attempt(self) -> bool:
        """True when a transient failure now would be final."""
        return self.attempts >= self.max_attempts

    async def checkpoint(self, step: str) -> None:
        """Enter `step`: extend the lease, record the step, and honour cancellation.

        Raises LeaseLost if another worker owns the job now and JobCancelled if the cancel flag is
        set. Call this between steps, never in the middle of one.
        """
        async with session_scope(self.factory) as session:
            jobs = JobsRepo(session)
            owned = await jobs.heartbeat(
                self.job_id, self.worker_id, now=self.clock(), lease_seconds=self.lease_seconds
            )
            if not owned:
                raise LeaseLost(f"job {self.job_id} is no longer held by {self.worker_id}")
            await jobs.set_step(self.job_id, step, now=self.clock())
            job = await jobs.get(self.job_id)
        self.log.info("job.step", step=step)
        if job is not None and job.cancel_requested:
            raise JobCancelled(f"job {self.job_id} was cancelled before step {step}")

    async def save_progress(self, session: AsyncSession, progress: dict[str, Any]) -> None:
        """Store progress inside the caller's transaction so a retry can resume from it."""
        stored = await JobsRepo(session).set_progress(
            self.job_id, progress, self.worker_id, now=self.clock()
        )
        if not stored:
            raise LeaseLost(f"job {self.job_id} is no longer held by {self.worker_id}")
        self.progress = progress

    async def finish(
        self,
        session: AsyncSession,
        status: JobStatus,
        *,
        result_ref: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Move the job to a terminal state in the caller's transaction (rolls back if not ours)."""
        done = await JobsRepo(session).finish(
            self.job_id,
            status,
            result_ref=result_ref,
            error=error,
            now=self.clock(),
            worker_id=self.worker_id,
        )
        if not done:
            raise LeaseLost(f"job {self.job_id} is no longer held by {self.worker_id}")


Handler = Callable[[JobContext], Awaitable[None]]


async def draft_not_available(ctx: JobContext) -> None:
    """Kept for tests of a registry with no drafting: fails cleanly, no retry."""
    raise PermanentJobError("draft_not_available", "no drafting handler is registered")


class HandlerRegistry:
    """Maps a job kind to its handler."""

    def __init__(self, handlers: dict[JobKind, Handler] | None = None) -> None:
        self._handlers: dict[JobKind, Handler] = dict(handlers or {})

    def register(self, kind: JobKind, handler: Handler) -> None:
        """Set (or replace) the handler for a kind."""
        self._handlers[kind] = handler

    def get(self, kind: JobKind) -> Handler:
        """The handler for a kind; PermanentJobError if none is registered."""
        handler = self._handlers.get(kind)
        if handler is None:
            raise PermanentJobError("no_handler", f"no handler registered for {kind.value}")
        return handler


def default_registry() -> HandlerRegistry:
    """Analyze runs the pipeline; draft runs the gated drafting agent (offline unless live)."""
    from cso.jobs.analyze import run_analyze
    from cso.jobs.draft_handler import run_draft_job

    return HandlerRegistry({JobKind.ANALYZE: run_analyze, JobKind.DRAFT: run_draft_job})

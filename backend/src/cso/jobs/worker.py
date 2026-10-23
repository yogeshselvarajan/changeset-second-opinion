"""The worker: claim a due job, run its handler under a hard cap, retry or finish it.

Retry policy: at most `max_attempts` (3) attempts; after a transient failure
the job goes back to `queued` with `run_after` set 5 / 20 / 60 s ahead (+/- 20 % jitter); a
permanent failure, or the last attempt failing, ends the job `failed(code)`. Cancellation is
checked between steps; a worker that lost its lease stops without touching the job.
"""

from __future__ import annotations

import random
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import anyio
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.config import CommunityConfig
from cso.domain.enums import CaseStatus, JobKind, JobStatus
from cso.jobs.analyze import revert_case_if_unanalyzed
from cso.jobs.deps import Deps
from cso.jobs.errors import JobCancelled, LeaseLost, classify
from cso.jobs.handlers import HandlerRegistry, JobContext, default_registry
from cso.jobs.reaper import reaper_loop
from cso.jobs.states import (
    DEFAULT_CONCURRENCY,
    HARD_CAP_S,
    LEASE_SECONDS,
    POLL_INTERVAL_S,
    REAPER_INTERVAL_S,
    backoff_seconds,
)
from cso.observability.context import log_context
from cso.observability.metrics import JOB_FAILURES, METRICS
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo, CasesRepo, ConfigsRepo, JobsRepo
from cso.persistence.tables import JobRow, utcnow


@dataclass(frozen=True)
class JobOutcome:
    """What happened to one claimed job after this attempt."""

    job_id: uuid.UUID
    kind: JobKind
    status: JobStatus  # queued means a retry was scheduled
    error: str | None
    attempts: int
    result_ref: dict[str, Any] | None


class Worker:
    """Polls the job table; `concurrency` jobs overlap, Decider calls never do."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        deps: Deps,
        *,
        registry: HandlerRegistry | None = None,
        worker_id: str | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        poll_interval_s: float = POLL_INTERVAL_S,
        lease_seconds: int = LEASE_SECONDS,
        reaper_interval_s: float = REAPER_INTERVAL_S,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
        rng: Callable[[], float] = random.random,
        hard_caps: dict[JobKind, float] | None = None,
    ) -> None:
        self.factory = factory
        self.deps = deps
        self.registry = registry or default_registry()
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.concurrency = max(1, concurrency)
        self.poll_interval_s = poll_interval_s
        self.lease_seconds = lease_seconds
        self.reaper_interval_s = reaper_interval_s
        self.clock = clock
        self._sleep = sleep
        self._rng = rng
        self._hard_caps = {**HARD_CAP_S, **(hard_caps or {})}
        self.outcomes: list[JobOutcome] = []
        self._log = structlog.get_logger().bind(worker=self.worker_id)

    # ------------------------------------------------------------------ setup and claiming

    async def ensure_config(self) -> None:
        """Make sure the started-with config version is stored, and one version is active.

        A pack an admin activated earlier stays active across a restart: this only activates the
        started-with version when nothing is active yet.
        """
        async with session_scope(self.factory) as session:
            repo = ConfigsRepo(session)
            await repo.add_if_absent(self.deps.config, self.deps.config_yaml, now=self.clock())
            if await repo.get_active() is None:
                await repo.activate(self.deps.config.version)

    async def active_config(self) -> CommunityConfig:
        """The configuration an admin has activated, else the one this worker started with.

        The stored version name is kept as is: runs reference it, and a version stored by earlier
        code may carry a hash made by an earlier scheme.
        """
        try:
            async with session_scope(self.factory) as session:
                row = await ConfigsRepo(session).get_active()
            if row is None or row.version == self.deps.config.version:
                return self.deps.config
            config = CommunityConfig.from_yaml_text(row.yaml, source=f"stored config {row.version}")
            return config.model_copy(update={"version": row.version})
        except Exception as exc:  # a broken stored config must not stop analysis
            self._log.warning("worker.active_config_unreadable", error=str(exc)[:200])
            return self.deps.config

    async def claim(self) -> JobRow | None:
        """Atomically take the next due job, or None."""
        async with session_scope(self.factory) as session:
            return await JobsRepo(session).claim(
                self.worker_id, now=self.clock(), lease_seconds=self.lease_seconds
            )

    # ------------------------------------------------------------------ running one job

    async def process(self, job: JobRow) -> JobOutcome:
        """Run one claimed job to its next resting state and report it.

        Every log line written meanwhile (the worker's, the pipeline's and the adapters') carries
        the request id of the API call that queued the job, plus the job and case ids.
        """
        with log_context(request_id=job.request_id, job_id=job.id, case_id=job.case_id):
            return await self._process(job)

    async def _process(self, job: JobRow) -> JobOutcome:
        kind = JobKind(job.kind)
        log = self._log.bind(job_id=str(job.id), case_id=str(job.case_id), kind=kind.value)
        ctx = JobContext(
            job_id=job.id,
            case_id=job.case_id,
            kind=kind,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            response_type=job.response_type,
            run_id=job.run_id,
            worker_id=self.worker_id,
            factory=self.factory,
            deps=self.deps,
            clock=self.clock,
            log=log,
            lease_seconds=self.lease_seconds,
            progress=dict(job.result_ref) if isinstance(job.result_ref, dict) else None,
            config=await self.active_config(),
        )
        log.info("job.claimed", attempt=job.attempts, max_attempts=job.max_attempts)
        try:
            handler = self.registry.get(kind)
            with anyio.fail_after(self._hard_caps[kind]):
                await handler(ctx)
            await self._complete_if_running(ctx)
        except JobCancelled:
            await self._finish_terminal(ctx, JobStatus.CANCELLED, None, "job.cancelled")
        except LeaseLost as exc:
            log.warning("job.lease_lost", detail=str(exc))
        except Exception as exc:
            await self._fail_or_retry(ctx, exc)
        outcome = await self._outcome(ctx)
        self.outcomes.append(outcome)
        log.info("job.attempt_done", status=outcome.status.value, error=outcome.error)
        return outcome

    async def _outcome(self, ctx: JobContext) -> JobOutcome:
        async with session_scope(self.factory) as session:
            row = await JobsRepo(session).get(ctx.job_id)
        if row is None:  # purged underneath us
            return JobOutcome(
                ctx.job_id, ctx.kind, JobStatus.FAILED, "job_missing", ctx.attempts, None
            )
        return JobOutcome(
            job_id=row.id,
            kind=ctx.kind,
            status=JobStatus(row.status),
            error=row.last_error,
            attempts=row.attempts,
            result_ref=row.result_ref,
        )

    async def _complete_if_running(self, ctx: JobContext) -> None:
        """A handler that returned without finishing the job succeeded."""
        async with session_scope(self.factory) as session:
            jobs = JobsRepo(session)
            row = await jobs.get(ctx.job_id)
            if (
                row is not None
                and row.status == JobStatus.RUNNING.value
                and row.locked_by == self.worker_id
            ):
                await jobs.finish(
                    ctx.job_id,
                    JobStatus.SUCCEEDED,
                    result_ref=row.result_ref,
                    now=self.clock(),
                    worker_id=self.worker_id,
                )

    async def _fail_or_retry(self, ctx: JobContext, exc: BaseException) -> None:
        verdict = classify(exc)
        ctx.log.warning(
            "job.attempt_failed",
            code=verdict.code,
            retry=verdict.retry,
            attempt=ctx.attempts,
            detail=verdict.detail,
        )
        if verdict.retry and not ctx.last_attempt:
            delay = backoff_seconds(ctx.attempts, self._rng())
            run_after = self.clock() + timedelta(seconds=delay)
            try:
                async with session_scope(self.factory) as session:
                    released = await JobsRepo(session).release_for_retry(
                        ctx.job_id,
                        error=verdict.code,
                        run_after=run_after,
                        now=self.clock(),
                        worker_id=self.worker_id,
                    )
                    if not released:
                        raise LeaseLost(str(ctx.job_id))
                    await AuditRepo(session).append(
                        actor=f"system:worker:{self.worker_id}",
                        action="job.retry_scheduled",
                        case_id=ctx.case_id,
                        payload={
                            "job_id": str(ctx.job_id),
                            "code": verdict.code,
                            "attempt": ctx.attempts,
                            "retry_in_s": round(delay, 1),
                        },
                        now=self.clock(),
                    )
            except LeaseLost:
                ctx.log.warning("job.lease_lost_on_retry")
            return
        await self._finish_terminal(ctx, JobStatus.FAILED, verdict.code, "job.failed")

    async def _finish_terminal(
        self, ctx: JobContext, status: JobStatus, error: str | None, action: str
    ) -> None:
        """Finish as failed or cancelled, audit it, and un-stick a case that never got a run."""
        if status is JobStatus.FAILED:
            METRICS.inc(JOB_FAILURES, kind=ctx.kind.value, code=error or "unknown")
        try:
            async with session_scope(self.factory) as session:
                # keep what an attempt saved (a draft's Bedrock spend must survive its failure)
                held = await JobsRepo(session).get(ctx.job_id)
                kept = held.result_ref if held is not None and held.result_ref else None
                await ctx.finish(session, status, result_ref=kept, error=error)
                cases = CasesRepo(session)
                case = await cases.get(ctx.case_id)
                if case is not None and ctx.kind is JobKind.ANALYZE:
                    back = revert_case_if_unanalyzed(case.status, case.latest_run_id)
                    if back is not None and back is CaseStatus.NEW:
                        await cases.set_status(ctx.case_id, back, now=self.clock())
                await AuditRepo(session).append(
                    actor=f"system:worker:{self.worker_id}",
                    action=action,
                    case_id=ctx.case_id,
                    payload={
                        "job_id": str(ctx.job_id),
                        "kind": ctx.kind.value,
                        "error": error,
                        "attempts": ctx.attempts,
                    },
                    now=self.clock(),
                )
        except LeaseLost:
            ctx.log.warning("job.lease_lost_on_finish")

    # ------------------------------------------------------------------ loops

    async def _run_slot(self, job: JobRow, slots: anyio.Semaphore) -> None:
        try:
            await self.process(job)
        except Exception:
            self._log.exception("job.worker_error", job_id=str(job.id))
        finally:
            slots.release()

    async def run_until_idle(self) -> list[JobOutcome]:
        """Process every currently due job (up to `concurrency` at once), then return.

        Jobs scheduled for a later retry stay queued; tests move the injected clock to reach them.
        """
        first = len(self.outcomes)
        await self.ensure_config()
        slots = anyio.Semaphore(self.concurrency)
        async with anyio.create_task_group() as tg:
            while True:
                await slots.acquire()
                job = await self.claim()
                if job is None:
                    slots.release()
                    break
                tg.start_soon(self._run_slot, job, slots)
        return self.outcomes[first:]

    async def run_once(self) -> JobOutcome | None:
        """Claim and run at most one due job."""
        await self.ensure_config()
        job = await self.claim()
        return None if job is None else await self.process(job)

    async def run_forever(self, stop: anyio.Event | None = None) -> None:
        """Poll until `stop` is set (or the task is cancelled); runs the reaper alongside."""
        await self.ensure_config()
        slots = anyio.Semaphore(self.concurrency)
        reaper_stop = anyio.Event()
        failures = 0
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                partial(
                    reaper_loop,
                    self.factory,
                    interval_s=self.reaper_interval_s,
                    clock=self.clock,
                    sleep=self._sleep,
                    log=self._log,
                    stop=reaper_stop,
                )
            )
            try:
                while stop is None or not stop.is_set():
                    await slots.acquire()
                    try:
                        job = await self.claim()
                        failures = 0
                    except Exception:
                        failures += 1
                        self._log.exception("jobs.claim_failed")
                        slots.release()
                        await self._sleep(min(30.0, self.poll_interval_s * 2**failures))
                        continue
                    if job is None:
                        slots.release()
                        await self._sleep(self.poll_interval_s)
                        continue
                    tg.start_soon(self._run_slot, job, slots)
                for _ in range(self.concurrency):  # let in-flight jobs finish
                    await slots.acquire()
            finally:
                reaper_stop.set()  # the reaper finishes any pass in progress, then exits

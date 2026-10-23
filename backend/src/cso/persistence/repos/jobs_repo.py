"""Durable job queue primitives: enqueue, claim, lease heartbeat, retry, cancel, reap, purge.

This is the only module with dialect-specific SQL: Postgres claims with
`FOR UPDATE SKIP LOCKED`, SQLite with a single-writer `UPDATE ... WHERE id=(SELECT ...)`. Both are
built from Core constructs so datetimes pass through `UTCDateTime` on either dialect. Job
behaviour (the step pipeline, cancellation points) belongs to the worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.enums import JobKind, JobStatus
from cso.persistence.repos._common import rowcount, utcnow
from cso.persistence.tables import JobRow

DEFAULT_LEASE_SECONDS = 300
LEASE_EXPIRED = "lease_expired"
_TERMINAL = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value)


def make_job_key(
    case_id: UUID,
    kind: JobKind,
    evidence_version: str | None,
    run_id: UUID | None,
    response_type: str | None,
) -> str:
    """Deduplication key: (case, kind, evidence_version, run_id, response_type), NULL as ''."""
    return "|".join(
        [
            str(case_id),
            kind.value,
            evidence_version or "",
            "" if run_id is None else str(run_id),
            response_type or "",
        ]
    )


def build_claim_statement(
    dialect_name: str, *, worker_id: str, now: datetime, lease_expires_at: datetime
) -> sa.Executable:
    """UPDATE that claims the next due queued job and returns its id (one statement, atomic)."""
    due = (
        sa.select(JobRow.id)
        .where(JobRow.status == JobStatus.QUEUED.value, JobRow.run_after <= now)
        .order_by(JobRow.priority.desc(), JobRow.created_at)
        .limit(1)
    )
    claim: dict[str, Any] = {
        "status": JobStatus.RUNNING.value,
        "attempts": JobRow.attempts + 1,
        "locked_by": worker_id,
        "locked_at": now,
        "lease_expires_at": lease_expires_at,
        "updated_at": now,
    }
    if dialect_name == "postgresql":
        nxt = due.with_for_update(skip_locked=True).cte("next")
        return (
            sa.update(JobRow)
            .where(JobRow.id == nxt.c.id)
            .values(**claim)
            .returning(JobRow.id)
            .execution_options(synchronize_session=False)
        )
    # SQLite: one writer at a time (WAL + busy_timeout); the status re-check guards the race.
    return (
        sa.update(JobRow)
        .where(JobRow.id == due.scalar_subquery(), JobRow.status == JobStatus.QUEUED.value)
        .values(**claim)
        .returning(JobRow.id)
        .execution_options(synchronize_session=False)
    )


@dataclass(frozen=True)
class ReapResult:
    """What one reaper pass did to jobs whose lease expired."""

    requeued: int
    failed: int


class JobsRepo:
    """Job rows. Unlike the immutable tables these are updated as the state machine advances."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def enqueue(
        self,
        case_id: UUID,
        kind: JobKind,
        *,
        evidence_version: str | None = None,
        run_id: UUID | None = None,
        response_type: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[JobRow, bool]:
        """Insert a queued job unless one with the same key exists; returns (job, created)."""
        key = make_job_key(case_id, kind, evidence_version, run_id, response_type)
        existing = await self.get_by_key(key)
        if existing is not None:
            return existing, False
        stamp = now or utcnow()
        row = JobRow(
            id=uuid4(),
            case_id=case_id,
            kind=kind.value,
            evidence_version=evidence_version,
            response_type=response_type,
            run_id=run_id,
            job_key=key,
            status=JobStatus.QUEUED.value,
            priority=priority,
            max_attempts=max_attempts,
            request_id=request_id,
            run_after=stamp,
            created_at=stamp,
            updated_at=stamp,
        )
        self._s.add(row)
        await self._s.flush()
        return row, True

    async def get(self, job_id: UUID) -> JobRow | None:
        """The job, reloaded from the database."""
        return await self._s.get(JobRow, job_id, populate_existing=True)

    async def get_by_key(self, job_key: str) -> JobRow | None:
        """The job with this deduplication key."""
        result = await self._s.execute(sa.select(JobRow).where(JobRow.job_key == job_key))
        return result.scalars().first()

    async def list_for_case(self, case_id: UUID, kind: JobKind | None = None) -> list[JobRow]:
        """Jobs of a case in creation order, optionally of one kind."""
        stmt = sa.select(JobRow).where(JobRow.case_id == case_id)
        if kind is not None:
            stmt = stmt.where(JobRow.kind == kind.value)
        result = await self._s.execute(stmt.order_by(JobRow.created_at, JobRow.id))
        return list(result.scalars())

    async def set_progress(
        self,
        job_id: UUID,
        progress: dict[str, Any],
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Store step progress (e.g. the snapshot id) so a retry can resume; False if not ours."""
        return (
            await rowcount(
                self._s,
                sa.update(JobRow)
                .where(
                    JobRow.id == job_id,
                    JobRow.locked_by == worker_id,
                    JobRow.status == JobStatus.RUNNING.value,
                )
                .values(result_ref=progress, updated_at=now or utcnow())
                .execution_options(synchronize_session=False),
            )
            > 0
        )

    async def active_for_case(self, case_id: UUID) -> list[JobRow]:
        """Queued or running jobs of a case."""
        result = await self._s.execute(
            sa.select(JobRow)
            .where(
                JobRow.case_id == case_id,
                JobRow.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
            )
            .order_by(JobRow.created_at)
        )
        return list(result.scalars())

    async def claim(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> JobRow | None:
        """Atomically take the next due job (priority desc, then oldest); None if none is due."""
        stamp = now or utcnow()
        bind = self._s.get_bind()
        statement = build_claim_statement(
            bind.dialect.name,
            worker_id=worker_id,
            now=stamp,
            lease_expires_at=stamp + timedelta(seconds=lease_seconds),
        )
        claimed = (await self._s.execute(statement)).scalars().first()
        if claimed is None:
            return None
        return await self._s.get(JobRow, claimed, populate_existing=True)

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        """Extend the lease; False when this worker no longer holds the job."""
        stamp = now or utcnow()
        return (
            await rowcount(
                self._s,
                sa.update(JobRow)
                .where(
                    JobRow.id == job_id,
                    JobRow.locked_by == worker_id,
                    JobRow.status == JobStatus.RUNNING.value,
                )
                .values(lease_expires_at=stamp + timedelta(seconds=lease_seconds), updated_at=stamp)
                .execution_options(synchronize_session=False),
            )
            > 0
        )

    async def set_step(self, job_id: UUID, step: str, *, now: datetime | None = None) -> None:
        """Record which pipeline step a running job is in."""
        await self._s.execute(
            sa.update(JobRow)
            .where(JobRow.id == job_id)
            .values(step=step, updated_at=now or utcnow())
            .execution_options(synchronize_session=False)
        )

    async def finish(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        result_ref: dict[str, Any] | None = None,
        error: str | None = None,
        now: datetime | None = None,
        worker_id: str | None = None,
    ) -> bool:
        """Move a queued or running job to a terminal state and release its lease.

        With `worker_id` the job must be running under that worker's lock, so a worker whose lease
        expired (and whose job was re-queued or claimed by another worker) cannot finish it.
        """
        if status.value not in _TERMINAL:
            raise ValueError(f"{status.value} is not a terminal job status")
        owned: list[sa.ColumnElement[bool]] = (
            [] if worker_id is None else [JobRow.locked_by == worker_id]
        )
        return (
            await rowcount(
                self._s,
                sa.update(JobRow)
                .where(
                    JobRow.id == job_id,
                    JobRow.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
                    *owned,
                )
                .values(
                    status=status.value,
                    result_ref=result_ref,
                    last_error=error,
                    locked_by=None,
                    locked_at=None,
                    lease_expires_at=None,
                    updated_at=now or utcnow(),
                )
                .execution_options(synchronize_session=False),
            )
            > 0
        )

    async def release_for_retry(
        self,
        job_id: UUID,
        *,
        error: str,
        run_after: datetime,
        now: datetime | None = None,
        worker_id: str | None = None,
    ) -> bool:
        """Put a running job back in the queue to run again after `run_after`.

        With `worker_id` the job must be running under that worker's lock.
        """
        owned: list[sa.ColumnElement[bool]] = (
            [] if worker_id is None else [JobRow.locked_by == worker_id]
        )
        return (
            await rowcount(
                self._s,
                sa.update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.RUNNING.value, *owned)
                .values(
                    status=JobStatus.QUEUED.value,
                    last_error=error,
                    run_after=run_after,
                    locked_by=None,
                    locked_at=None,
                    lease_expires_at=None,
                    updated_at=now or utcnow(),
                )
                .execution_options(synchronize_session=False),
            )
            > 0
        )

    async def request_cancel(self, job_id: UUID, *, now: datetime | None = None) -> JobRow | None:
        """Cancel a queued job at once; flag a running one for the worker to stop at a step."""
        stamp = now or utcnow()
        cancelled = await rowcount(
            self._s,
            sa.update(JobRow)
            .where(JobRow.id == job_id, JobRow.status == JobStatus.QUEUED.value)
            .values(status=JobStatus.CANCELLED.value, cancel_requested=True, updated_at=stamp)
            .execution_options(synchronize_session=False),
        )
        if not cancelled:
            await self._s.execute(
                sa.update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.RUNNING.value)
                .values(cancel_requested=True, updated_at=stamp)
                .execution_options(synchronize_session=False)
            )
        return await self.get(job_id)

    async def requeue_expired(self, *, now: datetime | None = None) -> ReapResult:
        """Reaper pass: expired leases go back to queued, or fail once attempts are used up."""
        stamp = now or utcnow()
        expired = (JobRow.status == JobStatus.RUNNING.value, JobRow.lease_expires_at < stamp)
        failed = await rowcount(
            self._s,
            sa.update(JobRow)
            .where(*expired, JobRow.attempts >= JobRow.max_attempts)
            .values(
                status=JobStatus.FAILED.value,
                last_error=LEASE_EXPIRED,
                locked_by=None,
                locked_at=None,
                lease_expires_at=None,
                updated_at=stamp,
            )
            .execution_options(synchronize_session=False),
        )
        requeued = await rowcount(
            self._s,
            sa.update(JobRow)
            .where(*expired, JobRow.attempts < JobRow.max_attempts)
            .values(
                status=JobStatus.QUEUED.value,
                locked_by=None,
                locked_at=None,
                lease_expires_at=None,
                updated_at=stamp,
            )
            .execution_options(synchronize_session=False),
        )
        return ReapResult(requeued=requeued, failed=failed)

    async def purge_terminal(self, older_than: datetime) -> int:
        """Delete terminal jobs last touched before `older_than` (default retention: 14 days)."""
        return await rowcount(
            self._s,
            sa.delete(JobRow)
            .where(JobRow.status.in_(_TERMINAL), JobRow.updated_at < older_than)
            .execution_options(synchronize_session=False),
        )

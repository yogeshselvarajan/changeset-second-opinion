"""Job queue primitives: dedupe, claim order, leases, reaper, retry, cancel, purge."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from persistence_support import make_result, store_case
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import JobKind, JobStatus
from cso.domain.models import EvidenceSnapshot
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, JobsRepo, RunsRepo
from cso.persistence.repos.jobs_repo import LEASE_EXPIRED, build_claim_statement, make_job_key

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


async def _case(
    factory: async_sessionmaker[AsyncSession], changeset_id: int = 900000000001
) -> UUID:
    async with session_scope(factory) as s:
        case, _ = await CasesRepo(s).get_or_create(changeset_id)
        return case.id


async def test_enqueue_dedupes_by_key(factory: async_sessionmaker[AsyncSession]) -> None:
    case_id = await _case(factory)
    run_id = uuid4()
    async with session_scope(factory) as s:
        jobs = JobsRepo(s)
        a, a_new = await jobs.enqueue(case_id, JobKind.ANALYZE, evidence_version="v1", now=NOW)
        b, b_new = await jobs.enqueue(case_id, JobKind.ANALYZE, evidence_version="v1", now=NOW)
        d1, d1_new = await jobs.enqueue(
            case_id, JobKind.DRAFT, evidence_version="v1", run_id=run_id, response_type="welcome"
        )
        d2, d2_new = await jobs.enqueue(
            case_id, JobKind.DRAFT, evidence_version="v1", run_id=run_id, response_type="ask"
        )
    assert a_new and not b_new and d1_new and d2_new
    assert a.id == b.id
    assert len({a.id, d1.id, d2.id}) == 3
    assert make_job_key(case_id, JobKind.ANALYZE, "v1", None, None) == a.job_key


async def test_claim_takes_highest_priority_then_oldest(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    ids: dict[str, UUID] = {}
    async with session_scope(factory) as s:
        cases = CasesRepo(s)
        jobs = JobsRepo(s)
        for name, changeset, priority, minutes in [
            ("old-low", 1, 0, 0),
            ("new-high", 2, 5, 3),
            ("old-high", 3, 5, 1),
        ]:
            case, _ = await cases.get_or_create(changeset)
            job, _ = await jobs.enqueue(
                case.id,
                JobKind.ANALYZE,
                priority=priority,
                now=NOW + timedelta(minutes=minutes),
            )
            ids[name] = job.id
    order: list[UUID] = []
    for _ in range(4):
        async with session_scope(factory) as s:
            claimed = await JobsRepo(s).claim("w1", now=NOW + timedelta(hours=1))
        if claimed is not None:
            order.append(claimed.id)
    assert order == [ids["old-high"], ids["new-high"], ids["old-low"]]


async def test_claim_sets_lease_and_counts_the_attempt(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    case_id = await _case(factory)
    async with session_scope(factory) as s:
        await JobsRepo(s).enqueue(case_id, JobKind.ANALYZE, now=NOW)
    async with session_scope(factory) as s:
        job = await JobsRepo(s).claim("worker-1", now=NOW, lease_seconds=60)
    assert job is not None
    assert job.status == JobStatus.RUNNING.value
    assert job.attempts == 1
    assert job.locked_by == "worker-1"
    assert job.lease_expires_at == NOW + timedelta(seconds=60)
    assert job.locked_at == NOW


async def test_claim_ignores_jobs_not_yet_due_and_returns_none_when_empty(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    case_id = await _case(factory)
    async with session_scope(factory) as s:
        assert await JobsRepo(s).claim("w", now=NOW) is None
        await JobsRepo(s).enqueue(case_id, JobKind.ANALYZE, now=NOW + timedelta(minutes=5))
    async with session_scope(factory) as s:
        assert await JobsRepo(s).claim("w", now=NOW) is None
        assert await JobsRepo(s).claim("w", now=NOW + timedelta(minutes=6)) is not None


async def test_concurrent_claims_never_take_the_same_job(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(factory) as s:
        cases = CasesRepo(s)
        for changeset in range(1, 7):
            case, _ = await cases.get_or_create(changeset)
            await JobsRepo(s).enqueue(case.id, JobKind.ANALYZE, now=NOW)

    async def worker(name: str) -> list[UUID]:
        taken: list[UUID] = []
        while True:
            async with session_scope(factory) as s:
                job = await JobsRepo(s).claim(name, now=NOW + timedelta(minutes=1))
            if job is None:
                return taken
            taken.append(job.id)

    results = await asyncio.gather(worker("a"), worker("b"), worker("c"))
    everything = [job_id for taken in results for job_id in taken]
    assert len(everything) == 6
    assert len(set(everything)) == 6


async def test_heartbeat_requires_the_lock_holder(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    case_id = await _case(factory)
    async with session_scope(factory) as s:
        await JobsRepo(s).enqueue(case_id, JobKind.ANALYZE, now=NOW)
    async with session_scope(factory) as s:
        job = await JobsRepo(s).claim("owner", now=NOW, lease_seconds=60)
        assert job is not None
        repo = JobsRepo(s)
        assert await repo.heartbeat(job.id, "intruder", now=NOW) is False
        assert await repo.heartbeat(job.id, "owner", now=NOW + timedelta(seconds=30)) is True
        refreshed = await repo.get(job.id)
    assert refreshed is not None
    assert refreshed.lease_expires_at == NOW + timedelta(seconds=30 + 300)


async def test_reaper_requeues_or_fails_expired_leases(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(factory) as s:
        cases, jobs = CasesRepo(s), JobsRepo(s)
        for changeset, max_attempts in [(1, 3), (2, 1), (3, 3)]:
            case, _ = await cases.get_or_create(changeset)
            await jobs.enqueue(case.id, JobKind.ANALYZE, max_attempts=max_attempts, now=NOW)
    claimed: list[UUID] = []
    for _ in range(3):
        async with session_scope(factory) as s:
            job = await JobsRepo(s).claim("w", now=NOW, lease_seconds=60)
            assert job is not None
            claimed.append(job.id)
    async with session_scope(factory) as s:
        # third job heartbeats past the reap time and must survive
        await JobsRepo(s).heartbeat(
            claimed[2], "w", now=NOW + timedelta(minutes=5), lease_seconds=600
        )
        result = await JobsRepo(s).requeue_expired(now=NOW + timedelta(minutes=5))
        by_id = {j: await JobsRepo(s).get(j) for j in claimed}
    assert (result.requeued, result.failed) == (1, 1)
    statuses = {j: row.status for j, row in by_id.items() if row is not None}
    assert statuses[claimed[0]] == JobStatus.QUEUED.value
    assert statuses[claimed[1]] == JobStatus.FAILED.value
    assert statuses[claimed[2]] == JobStatus.RUNNING.value
    failed = by_id[claimed[1]]
    assert failed is not None and failed.last_error == LEASE_EXPIRED
    requeued = by_id[claimed[0]]
    assert requeued is not None and requeued.attempts == 1 and requeued.locked_by is None


async def test_finish_retry_and_cancel(factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(factory) as s:
        cases, jobs = CasesRepo(s), JobsRepo(s)
        job_ids = []
        for changeset in (1, 2, 3, 4):
            case, _ = await cases.get_or_create(changeset)
            job, _ = await jobs.enqueue(case.id, JobKind.ANALYZE, now=NOW)
            job_ids.append(job.id)
    async with session_scope(factory) as s:
        repo = JobsRepo(s)
        for _ in range(4):
            assert await repo.claim("w", now=NOW) is not None
        done = await repo.finish(
            job_ids[0], JobStatus.SUCCEEDED, result_ref={"run_id": "r"}, now=NOW
        )
        retry = await repo.release_for_retry(
            job_ids[1], error="boom", run_after=NOW + timedelta(seconds=30), now=NOW
        )
        flagged = await repo.request_cancel(job_ids[2], now=NOW)
        again = await repo.finish(job_ids[0], JobStatus.FAILED)  # terminal jobs do not move
        succeeded = await repo.get(job_ids[0])
        retried = await repo.get(job_ids[1])
    assert done and retry and not again
    assert succeeded is not None and succeeded.result_ref == {"run_id": "r"}
    assert succeeded.locked_by is None
    assert retried is not None and retried.status == JobStatus.QUEUED.value
    assert retried.last_error == "boom" and retried.run_after == NOW + timedelta(seconds=30)
    assert flagged is not None and flagged.status == JobStatus.RUNNING.value
    assert flagged.cancel_requested is True


async def test_cancel_queued_job_is_immediate(factory: async_sessionmaker[AsyncSession]) -> None:
    case_id = await _case(factory)
    async with session_scope(factory) as s:
        job, _ = await JobsRepo(s).enqueue(case_id, JobKind.ANALYZE, now=NOW)
        cancelled = await JobsRepo(s).request_cancel(job.id, now=NOW)
        none_left = await JobsRepo(s).claim("w", now=NOW)
    assert cancelled is not None and cancelled.status == JobStatus.CANCELLED.value
    assert none_left is None


async def test_finish_rejects_non_terminal_status(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    import pytest

    async with factory() as s:
        with pytest.raises(ValueError, match="terminal"):
            await JobsRepo(s).finish(uuid4(), JobStatus.RUNNING)


async def test_purge_removes_old_terminal_jobs_but_keeps_runs(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    from persistence_support import config

    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
        job, _ = await JobsRepo(s).enqueue(stored.case_id, JobKind.ANALYZE, now=NOW)
        run_id = await RunsRepo(s).add(
            stored.case_id,
            stored.snapshot_id,
            make_result(config()[0].version, snapshot_id=stored.snapshot_id),
            job_id=job.id,
        )
        await JobsRepo(s).claim("w", now=NOW)
        await JobsRepo(s).finish(job.id, JobStatus.SUCCEEDED, now=NOW)
    async with session_scope(factory) as s:
        purged = await JobsRepo(s).purge_terminal(NOW + timedelta(days=14))
    assert purged == 1
    async with factory() as s:
        row = await RunsRepo(s).get_row(run_id)
        remaining = (await s.execute(sa.text("SELECT count(*) FROM jobs"))).scalar_one()
    assert row is not None and row.job_id is None  # referential SET NULL, not an app UPDATE
    assert remaining == 0


def test_postgres_claim_uses_skip_locked_and_the_cte_form() -> None:
    stmt = build_claim_statement(
        "postgresql", worker_id="w", now=NOW, lease_expires_at=NOW + timedelta(minutes=5)
    )
    sql = str(stmt.compile(dialect=postgresql.psycopg.dialect())).upper()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "WITH NEXT AS" in sql.replace('"', "")
    assert "RETURNING" in sql
    assert "ORDER BY JOBS.PRIORITY DESC, JOBS.CREATED_AT" in sql.replace('"', "")


def test_sqlite_claim_is_a_single_update_with_a_status_guard() -> None:
    stmt = build_claim_statement(
        "sqlite", worker_id="w", now=NOW, lease_expires_at=NOW + timedelta(minutes=5)
    )
    sql = str(stmt.compile(dialect=sqlite.dialect())).upper()
    assert sql.startswith("UPDATE JOBS SET")
    assert "SKIP LOCKED" not in sql
    assert "FOR UPDATE" not in sql
    assert "RETURNING" in sql
    assert sql.count("JOBS.STATUS =") >= 2  # picked row is re-checked inside the UPDATE

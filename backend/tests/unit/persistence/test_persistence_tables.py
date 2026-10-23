"""Schema behaviour: pragmas, types, foreign keys and the unique constraints that dedupe work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from persistence_support import store_case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cso.domain.enums import JobKind
from cso.domain.models import EvidenceSnapshot
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, JobsRepo, SnapshotsRepo
from cso.persistence.tables import CommunityConfigRow, ReviewCaseRow


async def test_sqlite_pragmas_applied(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        mode = (await conn.execute(sa.text("PRAGMA journal_mode"))).scalar_one()
        timeout = (await conn.execute(sa.text("PRAGMA busy_timeout"))).scalar_one()
        fks = (await conn.execute(sa.text("PRAGMA foreign_keys"))).scalar_one()
    assert str(mode).lower() == "wal"
    assert timeout == 5000
    assert fks == 1


async def test_datetimes_round_trip_as_utc(factory: async_sessionmaker[AsyncSession]) -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    stamp = datetime(2026, 10, 17, 12, 0, tzinfo=ist)
    async with session_scope(factory) as s:
        case, _ = await CasesRepo(s).get_or_create(900000000001, now=stamp)
        case_id = case.id
    async with factory() as s:
        row = await s.get(ReviewCaseRow, case_id)
        assert row is not None
        assert row.created_at == stamp
        assert row.created_at.tzinfo is not None
        assert row.created_at.utcoffset() == timedelta(0)


async def test_naive_datetime_is_rejected(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as s:
        s.add(CommunityConfigRow(version="v", yaml="x", created_at=datetime(2026, 1, 1)))
        with pytest.raises(sa.exc.StatementError, match="naive datetime"):
            await s.flush()


async def test_json_round_trips(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
    async with factory() as s:
        loaded = await SnapshotsRepo(s).get(stored.snapshot_id)
    assert loaded is not None
    assert loaded.coverage == snapshot_01.coverage
    assert loaded.elements == snapshot_01.elements
    assert loaded.rendered_text == snapshot_01.rendered_text


async def test_foreign_keys_are_enforced(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as s:
        with pytest.raises(IntegrityError):
            await JobsRepo(s).enqueue(uuid4(), JobKind.ANALYZE, evidence_version="v1")


async def test_changeset_id_is_unique(factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(factory) as s:
        first, created = await CasesRepo(s).get_or_create(900000000001)
        again, created_again = await CasesRepo(s).get_or_create(900000000001)
    assert created and not created_again
    assert first.id == again.id
    async with factory() as s:
        s.add(ReviewCaseRow(changeset_id=900000000001))
        with pytest.raises(IntegrityError):
            await s.flush()


async def test_snapshot_version_is_unique_per_case(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
        again_id, created = await SnapshotsRepo(s).add(stored.case_id, snapshot_01)
    assert not created
    assert again_id == stored.snapshot_id
    async with session_scope(factory) as s:
        count = (await s.execute(sa.text("SELECT count(*) FROM evidence_snapshots"))).scalar_one()
    assert count == 1


async def test_raw_duplicate_snapshot_hits_the_database_constraint(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    from cso.persistence.tables import EvidenceSnapshotRow

    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
    async with factory() as s:
        s.add(
            EvidenceSnapshotRow(
                case_id=stored.case_id,
                evidence_version=snapshot_01.evidence_version,
                source="replay",
                fetched_at=datetime.now(UTC),
                coverage={},
                raw={},
                elements=[],
                tag_diffs=[],
                discussion=[],
            )
        )
        with pytest.raises(IntegrityError):
            await s.flush()


async def test_job_key_dedupes_even_with_null_columns(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(factory) as s:
        case, _ = await CasesRepo(s).get_or_create(900000000001)
        jobs = JobsRepo(s)
        first, created = await jobs.enqueue(case.id, JobKind.ANALYZE)
        second, created_again = await jobs.enqueue(case.id, JobKind.ANALYZE)
        other, other_created = await jobs.enqueue(case.id, JobKind.ANALYZE, evidence_version="v2")
    assert created and not created_again and other_created
    assert first.id == second.id != other.id

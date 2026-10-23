"""Snapshots, runs, drafts, outcomes and audit events cannot be updated or deleted."""

from __future__ import annotations

from uuid import UUID

import pytest
import sqlalchemy as sa
from persistence_support import Stored, store_case, store_draft
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import Disposition
from cso.domain.models import EvidenceSnapshot, OutcomeInput
from cso.persistence.db import session_scope
from cso.persistence.errors import ImmutableRowError
from cso.persistence.repos import AuditRepo, CasesRepo, OutcomesRepo
from cso.persistence.tables import (
    AnalysisRunRow,
    AuditEventRow,
    DraftRow,
    EvidenceSnapshotRow,
    HumanOutcomeRow,
    ReviewCaseRow,
)

ROW_TABLES: list[tuple[type, str, str, str]] = [
    (EvidenceSnapshotRow, "evidence_snapshots", "rendered_text", "changed"),
    (AnalysisRunRow, "analysis_runs", "lane", "looks_consistent"),
    (DraftRow, "drafts", "body", "edited"),
    (HumanOutcomeRow, "human_outcomes", "note", "edited"),
    (AuditEventRow, "audit_events", "action", "edited"),
]


async def _populate(
    factory: async_sessionmaker[AsyncSession], snapshot: EvidenceSnapshot
) -> tuple[Stored, UUID, int]:
    """One row in every immutable table; returns (stored, outcome_id, audit_id)."""
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot)
        await store_draft(s, stored)
        outcome = await OutcomesRepo(s).append(
            stored.case_id,
            OutcomeInput(disposition=Disposition.AGREE, run_id_seen=stored.run_id),
            reviewer_display="reviewer-a",
            session_id=None,
            expected_version=0,
        )
        audit = await AuditRepo(s).append(actor="reviewer-a", action="seed", case_id=stored.case_id)
    assert outcome.id is not None
    return stored, outcome.id, audit.id


@pytest.mark.parametrize(("model", "table", "column", "value"), ROW_TABLES)
async def test_orm_update_is_refused(
    factory: async_sessionmaker[AsyncSession],
    snapshot_01: EvidenceSnapshot,
    model: type,
    table: str,
    column: str,
    value: str,
) -> None:
    await _populate(factory, snapshot_01)
    async with factory() as s:
        row = (await s.execute(sa.select(model).limit(1))).scalars().one()
        setattr(row, column, value)
        with pytest.raises(ImmutableRowError, match=table):
            await s.flush()


@pytest.mark.parametrize(("model", "table", "column", "value"), ROW_TABLES)
async def test_orm_delete_is_refused(
    factory: async_sessionmaker[AsyncSession],
    snapshot_01: EvidenceSnapshot,
    model: type,
    table: str,
    column: str,
    value: str,
) -> None:
    await _populate(factory, snapshot_01)
    async with factory() as s:
        row = (await s.execute(sa.select(model).limit(1))).scalars().one()
        await s.delete(row)
        with pytest.raises(ImmutableRowError, match=table):
            await s.flush()


@pytest.mark.parametrize(("model", "table", "column", "value"), ROW_TABLES)
async def test_bulk_update_and_delete_are_refused(
    factory: async_sessionmaker[AsyncSession],
    snapshot_01: EvidenceSnapshot,
    model: type,
    table: str,
    column: str,
    value: str,
) -> None:
    await _populate(factory, snapshot_01)
    async with factory() as s:
        with pytest.raises(ImmutableRowError, match=table):
            await s.execute(sa.update(model).values({column: value}))
    async with factory() as s:
        with pytest.raises(ImmutableRowError, match=table):
            await s.execute(sa.delete(model))


@pytest.mark.parametrize(("model", "table", "column", "value"), ROW_TABLES)
async def test_raw_sql_is_refused_by_the_engine_guard(
    factory: async_sessionmaker[AsyncSession],
    snapshot_01: EvidenceSnapshot,
    model: type,
    table: str,
    column: str,
    value: str,
) -> None:
    await _populate(factory, snapshot_01)
    async with factory() as s:
        with pytest.raises(ImmutableRowError, match=table):
            await s.execute(sa.text(f"UPDATE {table} SET {column} = 'x'"))  # noqa: S608  # fixed names
    async with factory() as s:
        with pytest.raises(ImmutableRowError, match=table):
            await s.execute(sa.text(f'DELETE FROM "{table}"'))  # noqa: S608  # fixed names


async def test_rows_are_unchanged_after_refused_attempts(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    stored, _, _ = await _populate(factory, snapshot_01)
    async with factory() as s:
        row = await s.get(AnalysisRunRow, stored.run_id)
        assert row is not None
        row.lane = "looks_consistent"
        with pytest.raises(ImmutableRowError):
            await s.flush()
        await s.rollback()
    async with factory() as s:
        row = await s.get(AnalysisRunRow, stored.run_id)
        assert row is not None
        assert row.lane == "review_suggested"


async def test_inserts_are_allowed(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    stored, _, _ = await _populate(factory, snapshot_01)
    async with session_scope(factory) as s:
        await AuditRepo(s).append(actor="x", action="second", case_id=stored.case_id)
        await store_draft(s, stored)
    async with factory() as s:
        count = (await s.execute(sa.text("SELECT count(*) FROM audit_events"))).scalar_one()
    assert count == 2


async def test_mutable_tables_stay_updatable(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    stored, _, _ = await _populate(factory, snapshot_01)
    async with session_scope(factory) as s:
        await CasesRepo(s).mark_stale(stored.case_id)
    async with factory() as s:
        row = await s.get(ReviewCaseRow, stored.case_id)
        assert row is not None
        assert row.stale is True

"""Outcome appends: optimistic version bump, concurrent writers, history paging."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from persistence_support import Stored, store_case
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import CaseStatus, Disposition, Lane
from cso.domain.models import EvidenceSnapshot, OutcomeInput
from cso.persistence.db import session_scope
from cso.persistence.errors import NotFoundError, VersionConflictError
from cso.persistence.repos import OutcomesRepo
from cso.persistence.tables import HumanOutcomeRow, ReviewCaseRow


def _input(stored: Stored, disposition: Disposition = Disposition.AGREE) -> OutcomeInput:
    return OutcomeInput(disposition=disposition, run_id_seen=stored.run_id, note="n")


async def test_append_bumps_version_and_marks_decided(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01)
        repo = OutcomesRepo(s)
        assert await repo.current_version(stored.case_id) == 0
        outcome = await repo.append(
            stored.case_id,
            _input(stored),
            reviewer_display="reviewer-a",
            session_id=None,
            expected_version=0,
        )
        assert await repo.current_version(stored.case_id) == 1
    assert outcome.id is not None
    async with factory() as s:
        case = await s.get(ReviewCaseRow, stored.case_id)
        assert case is not None
        assert case.status == CaseStatus.DECIDED.value
        assert case.latest_outcome == "agree"
        latest = await OutcomesRepo(s).latest_for_case(stored.case_id)
    assert latest is not None
    assert latest.id == outcome.id
    assert latest.reviewer_display == "reviewer-a"


async def test_stale_version_conflicts_and_reports_the_current_one(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01)
        first = await OutcomesRepo(s).append(
            stored.case_id,
            _input(stored),
            reviewer_display="a",
            session_id=None,
            expected_version=0,
        )
    async with factory() as s:
        with pytest.raises(VersionConflictError) as caught:
            await OutcomesRepo(s).append(
                stored.case_id,
                _input(stored, Disposition.NO_ACTION),
                reviewer_display="b",
                session_id=None,
                expected_version=0,
            )
    assert caught.value.expected == 0
    assert caught.value.current == 1
    assert caught.value.current_outcome_id == first.id
    async with factory() as s:
        count = (
            await s.execute(sa.select(sa.func.count()).select_from(HumanOutcomeRow))
        ).scalar_one()
    assert count == 1


async def test_correction_with_the_new_version_is_a_new_row(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01)
        repo = OutcomesRepo(s)
        await repo.append(
            stored.case_id,
            _input(stored),
            reviewer_display="a",
            session_id=None,
            expected_version=0,
        )
        await repo.append(
            stored.case_id,
            _input(stored, Disposition.NEEDS_SURVEY),
            reviewer_display="a",
            session_id=None,
            expected_version=1,
        )
        history = await repo.list_for_case(stored.case_id)
    assert [o.disposition for o in history] == [Disposition.NEEDS_SURVEY, Disposition.AGREE]


async def test_unknown_case_is_not_found(factory: async_sessionmaker[AsyncSession]) -> None:
    from uuid import uuid4

    async with factory() as s:
        with pytest.raises(NotFoundError):
            await OutcomesRepo(s).append(
                uuid4(),
                OutcomeInput(disposition=Disposition.AGREE, run_id_seen=uuid4()),
                reviewer_display="a",
                session_id=None,
                expected_version=0,
            )


async def test_concurrent_stale_appends_one_wins(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01)

    async def attempt(name: str, hold: float) -> str:
        async with factory() as s:
            try:
                await OutcomesRepo(s).append(
                    stored.case_id,
                    _input(stored),
                    reviewer_display=name,
                    session_id=None,
                    expected_version=0,
                )
                await asyncio.sleep(hold)  # keep the write lock so the other writer overlaps
                await s.commit()
            except VersionConflictError:
                await s.rollback()
                return "conflict"
            return "won"

    results = await asyncio.gather(attempt("a", 0.3), attempt("b", 0.0))
    assert sorted(results) == ["conflict", "won"]
    async with factory() as s:
        rows = (await s.execute(sa.select(HumanOutcomeRow))).scalars().all()
        version = await OutcomesRepo(s).current_version(stored.case_id)
    assert len(rows) == 1
    assert version == 1


async def test_decision_history_pages_by_keyset(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    base = datetime(2026, 10, 17, tzinfo=UTC)
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, lane=Lane.NEEDS_LOCAL_KNOWLEDGE)
        repo = OutcomesRepo(s)
        for i in range(5):
            await repo.append(
                stored.case_id,
                _input(stored),
                reviewer_display="a" if i % 2 == 0 else "b",
                session_id=None,
                expected_version=i,
                now=base + timedelta(minutes=i),
            )
    async with factory() as s:
        repo = OutcomesRepo(s)
        first = await repo.list_decisions(None, 2)
        assert len(first.items) == 2 and first.next_cursor is not None
        second = await repo.list_decisions(first.next_cursor, 2)
        third = await repo.list_decisions(second.next_cursor, 2)
        only_a = await repo.list_decisions(None, 10, reviewer="a")
    seen = [d.outcome.id for d in (*first.items, *second.items, *third.items)]
    assert len(seen) == 5 and len(set(seen)) == 5
    assert third.next_cursor is None
    assert first.items[0].lane_at_decision is Lane.NEEDS_LOCAL_KNOWLEDGE
    assert first.items[0].changeset_id == stored.changeset_id
    assert len(only_a.items) == 3

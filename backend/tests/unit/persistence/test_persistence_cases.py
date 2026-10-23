"""Case repository: summary columns, queue ordering, keyset paging, filters, counts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from persistence_support import store_case
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import CaseStatus, Lane
from cso.domain.models import EvidenceSnapshot
from cso.persistence.db import session_scope
from cso.persistence.errors import NotFoundError
from cso.persistence.repos import CaseFilters, CasesRepo, lane_rank
from cso.persistence.repos.cases_repo import LANE_RANK

BASE = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


async def _make_cases(
    factory: async_sessionmaker[AsyncSession], specs: list[tuple[int, Lane, int]]
) -> None:
    """Create cases directly: (changeset_id, lane, minutes after BASE)."""
    async with session_scope(factory) as s:
        repo = CasesRepo(s)
        for changeset_id, lane, minutes in specs:
            case, _ = await repo.get_or_create(changeset_id, now=BASE + timedelta(minutes=minutes))
            case.lane = lane.value
            case.lane_rank = lane_rank(lane)


def test_every_lane_has_a_rank() -> None:
    assert set(LANE_RANK) == set(Lane)
    assert len(set(LANE_RANK.values())) == len(Lane)


async def test_apply_snapshot_copies_queue_facts(
    factory: async_sessionmaker[AsyncSession], snapshot_02: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_02, with_run=False)
        await CasesRepo(s).mark_stale(stored.case_id)
        await CasesRepo(s).apply_snapshot(stored.case_id, snapshot_02, stored.snapshot_id)
        case = await CasesRepo(s).get(stored.case_id)
    assert case is not None
    assert case.changeset_id == snapshot_02.changeset.id
    assert case.editor == snapshot_02.changeset.created_by
    assert case.latest_snapshot_id == stored.snapshot_id
    assert case.coverage_score == snapshot_02.coverage.score
    assert case.flags == snapshot_02.flags
    assert case.stale is False
    assert case.status == CaseStatus.NEW.value


async def test_record_run_sets_lane_rank_and_status(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, lane=Lane.LOOKS_CONSISTENT)
        case = await CasesRepo(s).get(stored.case_id)
    assert case is not None
    assert case.lane == "looks_consistent"
    assert case.lane_rank == lane_rank(Lane.LOOKS_CONSISTENT)
    assert case.latest_run_id == stored.run_id
    assert case.status == CaseStatus.ANALYZED.value
    assert case.band == "unsure"


def test_rule_r1_puts_a_case_ahead_of_every_lane() -> None:
    first = min(LANE_RANK.values())
    assert lane_rank(Lane.INSUFFICIENT_EVIDENCE, ["R1"]) < first
    assert lane_rank(Lane.LOOKS_CONSISTENT, ["R3", "R1"]) < first
    # Any other rule leaves the lane's own rank alone.
    assert lane_rank(Lane.INSUFFICIENT_EVIDENCE, ["R3"]) == LANE_RANK[Lane.INSUFFICIENT_EVIDENCE]


async def test_r1_case_is_listed_first_and_pages_stay_in_order(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _make_cases(
        factory,
        [
            (900000000020, Lane.REVIEW_SUGGESTED, 5),
            (900000000021, Lane.REVIEW_SUGGESTED, 4),
            (900000000022, Lane.INSUFFICIENT_EVIDENCE, 1),
        ],
    )
    async with session_scope(factory) as s:
        repo = CasesRepo(s)
        case, _ = await repo.get_or_create(900000000022, now=BASE)
        case.lane_rank = lane_rank(Lane.INSUFFICIENT_EVIDENCE, ["R1"])
    async with factory() as s:
        first = await CasesRepo(s).list_page(CaseFilters(), None, 1)
        assert [c.changeset_id for c in first.items] == [900000000022]
        assert first.next_cursor is not None
        second = await CasesRepo(s).list_page(CaseFilters(), first.next_cursor, 5)
    assert [c.changeset_id for c in second.items] == [900000000020, 900000000021]


async def test_unknown_case_raises(factory: async_sessionmaker[AsyncSession]) -> None:
    from uuid import uuid4

    async with factory() as s:
        with pytest.raises(NotFoundError):
            await CasesRepo(s).mark_stale(uuid4())


async def test_queue_orders_by_lane_then_newest_first(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _make_cases(
        factory,
        [
            (900000000010, Lane.LOOKS_CONSISTENT, 0),
            (900000000011, Lane.REVIEW_SUGGESTED, 1),
            (900000000012, Lane.REVIEW_SUGGESTED, 5),
            (900000000013, Lane.INSUFFICIENT_EVIDENCE, 3),
        ],
    )
    async with factory() as s:
        page = await CasesRepo(s).list_page(CaseFilters(), None, 10)
    assert [c.changeset_id for c in page.items] == [
        900000000012,
        900000000011,
        900000000013,
        900000000010,
    ]
    assert page.next_cursor is None


async def test_keyset_paging_visits_every_case_once(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    lanes = [Lane.REVIEW_SUGGESTED, Lane.NEEDS_LOCAL_KNOWLEDGE, Lane.LOOKS_CONSISTENT]
    await _make_cases(factory, [(900000000100 + i, lanes[i % 3], i) for i in range(11)])
    seen: list[int] = []
    cursor = None
    async with factory() as s:
        repo = CasesRepo(s)
        while True:
            page = await repo.list_page(CaseFilters(), cursor, 4)
            seen.extend(c.changeset_id for c in page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
    assert len(seen) == 11 and len(set(seen)) == 11


async def test_keyset_paging_is_stable_when_rows_are_inserted_between_pages(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _make_cases(factory, [(900000000200 + i, Lane.REVIEW_SUGGESTED, i) for i in range(6)])
    async with factory() as s:
        first = await CasesRepo(s).list_page(CaseFilters(), None, 3)
    assert first.next_cursor is not None
    # Newer rows arrive in the same lane and in a higher-priority-lane position between pages.
    await _make_cases(
        factory,
        [(900000000300, Lane.REVIEW_SUGGESTED, 60), (900000000301, Lane.REVIEW_SUGGESTED, 61)],
    )
    async with factory() as s:
        second = await CasesRepo(s).list_page(CaseFilters(), first.next_cursor, 10)
    seen = [c.changeset_id for c in (*first.items, *second.items)]
    assert len(seen) == len(set(seen))
    assert {900000000300, 900000000301}.isdisjoint(seen)  # newer rows sort before the cursor
    assert set(seen) == {900000000200 + i for i in range(6)}


async def test_filters_and_counts(factory: async_sessionmaker[AsyncSession]) -> None:
    await _make_cases(
        factory,
        [
            (900000000401, Lane.REVIEW_SUGGESTED, 0),
            (900000000402, Lane.REVIEW_SUGGESTED, 1),
            (900000000403, Lane.LOOKS_CONSISTENT, 2),
        ],
    )
    async with session_scope(factory) as s:
        repo = CasesRepo(s)
        case = await repo.get_by_changeset(900000000402)
        assert case is not None
        case.stale = True
        case.editor = "StreetComplete 61.0"
    async with factory() as s:
        repo = CasesRepo(s)
        by_lane = await repo.list_page(CaseFilters(lane=Lane.REVIEW_SUGGESTED), None, 10)
        stale = await repo.list_page(CaseFilters(stale=True), None, 10)
        by_q = await repo.list_page(CaseFilters(q="90000000040"), None, 10)
        by_editor_q = await repo.list_page(CaseFilters(q="Street"), None, 10)
        literal = await repo.list_page(CaseFilters(q="%"), None, 10)
        counts = await repo.counts_by_lane(CaseFilters(lane=Lane.LOOKS_CONSISTENT))
        status_counts = await repo.counts_by_lane(CaseFilters(status=CaseStatus.DECIDED))
    assert len(by_lane.items) == 2
    assert [c.changeset_id for c in stale.items] == [900000000402]
    assert len(by_q.items) == 3
    assert [c.changeset_id for c in by_editor_q.items] == [900000000402]
    assert literal.items == []  # wildcards are escaped, not interpreted
    assert counts[Lane.REVIEW_SUGGESTED] == 2  # a lane filter does not shrink the counts
    assert counts[Lane.LOOKS_CONSISTENT] == 1
    assert set(counts) == set(Lane)
    assert sum(status_counts.values()) == 0

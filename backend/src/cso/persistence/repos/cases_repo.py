"""Review cases: dedupe by changeset id, mutable pointers, queue listing with keyset paging."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.enums import Band, CaseStatus, ChangeAction, Lane, Nature, Response
from cso.domain.models import EvidenceSnapshot
from cso.persistence.errors import NotFoundError
from cso.persistence.repos._common import KeysetCursor, like_escape, utcnow
from cso.persistence.tables import ReviewCaseRow

# Provisional queue order (most reviewer attention first). Lane assignment belongs to the policy
# gate (domain/lanes.py); this only maps a lane to the integer the queue index sorts on.
LANE_RANK: dict[Lane, int] = {
    Lane.REVIEW_SUGGESTED: 0,
    Lane.INSUFFICIENT_EVIDENCE: 1,
    Lane.NEEDS_LOCAL_KNOWLEDGE: 2,
    Lane.RULES_ONLY: 3,
    Lane.LOOKS_CONSISTENT: 4,
}


#: Rule R1 (deletion of a mature feature) puts a case ahead of every lane: the person who would
#: look at it first should not have to scroll past simpler cases. It orders only; the case keeps
#: its lane, and nothing is hidden.
R1_PRIORITY_RANK = -1


def lane_rank(lane: Lane, rules_fired: Iterable[str] = ()) -> int:
    """Sort key of a case in the queue (lower sorts first): its lane, or first when R1 fired."""
    if "R1" in set(rules_fired):
        return R1_PRIORITY_RANK
    return LANE_RANK[lane]


@dataclass(frozen=True)
class CaseFilters:
    """Queue filters; every field is optional."""

    lane: Lane | None = None
    status: CaseStatus | None = None
    editor: str | None = None
    q: str | None = None
    stale: bool | None = None


@dataclass(frozen=True)
class CasePage:
    """One page of cases and the cursor of the next page, if there is one."""

    items: list[ReviewCaseRow]
    next_cursor: KeysetCursor | None


def _conditions(filters: CaseFilters) -> list[sa.ColumnElement[bool]]:
    cols = ReviewCaseRow
    out: list[sa.ColumnElement[bool]] = []
    if filters.lane is not None:
        out.append(cols.lane == filters.lane.value)
    if filters.status is not None:
        out.append(cols.status == filters.status.value)
    if filters.editor:
        out.append(cols.editor == filters.editor)
    if filters.stale is not None:
        out.append(cols.stale.is_(filters.stale))
    if filters.q:
        needle = like_escape(filters.q.strip())
        out.append(
            sa.or_(
                sa.cast(cols.changeset_id, sa.Text).like(f"{needle}%", escape="\\"),
                cols.editor.like(f"%{needle}%", escape="\\"),
                cols.place_label.like(f"%{needle}%", escape="\\"),
            )
        )
    return out


class CasesRepo:
    """Case rows. Counts and pointers change; identity (changeset id) never does."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, case_id: UUID) -> ReviewCaseRow | None:
        """The case, if it exists."""
        return await self._s.get(ReviewCaseRow, case_id)

    async def get_by_changeset(self, changeset_id: int) -> ReviewCaseRow | None:
        """The case for this changeset id, if it exists."""
        result = await self._s.execute(
            sa.select(ReviewCaseRow).where(ReviewCaseRow.changeset_id == changeset_id)
        )
        return result.scalars().first()

    async def get_or_create(
        self, changeset_id: int, *, now: datetime | None = None
    ) -> tuple[ReviewCaseRow, bool]:
        """Idempotent create keyed by changeset id; returns (case, created)."""
        existing = await self.get_by_changeset(changeset_id)
        if existing is not None:
            return existing, False
        stamp = now or utcnow()
        row = ReviewCaseRow(changeset_id=changeset_id, created_at=stamp, updated_at=stamp)
        self._s.add(row)
        await self._s.flush()
        return row, True

    async def _require(self, case_id: UUID) -> ReviewCaseRow:
        row = await self.get(case_id)
        if row is None:
            raise NotFoundError(f"case {case_id} does not exist")
        return row

    async def apply_snapshot(
        self,
        case_id: UUID,
        snapshot: EvidenceSnapshot,
        snapshot_id: UUID,
        *,
        now: datetime | None = None,
    ) -> ReviewCaseRow:
        """Copy the queue-facing facts of a new snapshot onto the case and clear `stale`."""
        row = await self._require(case_id)
        counts = snapshot.element_counts
        row.uid = snapshot.changeset.uid
        row.user_display = snapshot.changeset.user_display
        row.editor = snapshot.changeset.created_by
        comment = (snapshot.changeset.comment or "").strip()
        row.comment = comment[:280] or None
        row.element_create = counts.get(ChangeAction.CREATE, 0)
        row.element_modify = counts.get(ChangeAction.MODIFY, 0)
        row.element_delete = counts.get(ChangeAction.DELETE, 0)
        row.flags = list(snapshot.flags)
        row.coverage_score = snapshot.coverage.score
        row.latest_snapshot_id = snapshot_id
        row.stale = False
        row.updated_at = now or utcnow()
        await self._s.flush()
        return row

    async def set_place_label(self, case_id: UUID, place_label: str | None) -> None:
        """Name where the edit happened (a recorded demo case carries one; live cases have none)."""
        row = await self._require(case_id)
        row.place_label = place_label
        await self._s.flush()

    async def mark_stale(self, case_id: UUID, stale: bool = True) -> None:
        """Flag that the changeset changed upstream since the latest snapshot."""
        row = await self._require(case_id)
        row.stale = stale
        await self._s.flush()

    async def set_status(
        self, case_id: UUID, status: CaseStatus, *, now: datetime | None = None
    ) -> None:
        """Move the case through its lifecycle."""
        row = await self._require(case_id)
        row.status = status.value
        row.updated_at = now or utcnow()
        await self._s.flush()

    async def record_run(
        self,
        case_id: UUID,
        run_id: UUID,
        *,
        lane: Lane,
        band: Band | None,
        nature: Nature | None,
        response: Response | None,
        rules_fired: Iterable[str] = (),
        now: datetime | None = None,
    ) -> None:
        """Point the case at its newest run and copy the lane summary the queue sorts on."""
        row = await self._require(case_id)
        row.latest_run_id = run_id
        row.lane = lane.value
        row.lane_rank = lane_rank(lane, rules_fired)
        row.band = None if band is None else band.value
        row.nature = None if nature is None else nature.value
        row.response = None if response is None else response.value
        if row.status in (CaseStatus.NEW.value, CaseStatus.ANALYZING.value):
            row.status = CaseStatus.ANALYZED.value
        row.updated_at = now or utcnow()
        await self._s.flush()

    async def set_latest_draft(self, case_id: UUID, draft_id: UUID) -> None:
        """Point the case at its newest draft."""
        row = await self._require(case_id)
        row.latest_draft_id = draft_id
        await self._s.flush()

    async def list_page(
        self, filters: CaseFilters, cursor: KeysetCursor | None, limit: int
    ) -> CasePage:
        """Queue page ordered by (lane_rank, created_at desc, id); stable under inserts."""
        cols = ReviewCaseRow
        stmt = sa.select(cols).where(*_conditions(filters))
        if cursor is not None:
            rank = cursor.rank if cursor.rank is not None else 0
            stmt = stmt.where(
                sa.or_(
                    cols.lane_rank > rank,
                    sa.and_(
                        cols.lane_rank == rank,
                        sa.or_(
                            cols.created_at < cursor.created_at,
                            sa.and_(cols.created_at == cursor.created_at, cols.id > cursor.id),
                        ),
                    ),
                )
            )
        stmt = stmt.order_by(cols.lane_rank, cols.created_at.desc(), cols.id).limit(limit + 1)
        rows = list((await self._s.execute(stmt)).scalars())
        next_cursor: KeysetCursor | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = KeysetCursor(created_at=last.created_at, id=last.id, rank=last.lane_rank)
        return CasePage(items=rows, next_cursor=next_cursor)

    async def counts_by_lane(self, filters: CaseFilters) -> dict[Lane, int]:
        """Size of every lane under the filters, ignoring any lane filter itself."""
        cols = ReviewCaseRow
        without_lane = CaseFilters(
            status=filters.status, editor=filters.editor, q=filters.q, stale=filters.stale
        )
        stmt = (
            sa.select(cols.lane, sa.func.count())
            .where(*_conditions(without_lane))
            .group_by(cols.lane)
        )
        counts = {Lane(lane): int(n) for lane, n in (await self._s.execute(stmt)).all()}
        return {lane: counts.get(lane, 0) for lane in Lane}

    async def count(self) -> int:
        """Number of cases."""
        stmt = sa.select(sa.func.count()).select_from(ReviewCaseRow)
        return int((await self._s.execute(stmt)).scalar_one())

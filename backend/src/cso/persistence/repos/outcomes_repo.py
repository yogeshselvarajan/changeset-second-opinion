"""Human outcomes: append-only, with an optimistic lock on the case's `outcome_version`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.enums import Band, CaseStatus, Disposition, Lane
from cso.domain.models import HumanOutcome, OutcomeInput
from cso.persistence.errors import NotFoundError, VersionConflictError
from cso.persistence.repos._common import KeysetCursor, rowcount, utcnow
from cso.persistence.tables import (
    AnalysisRunRow,
    HumanOutcomeRow,
    ReviewCaseRow,
)


def outcome_to_model(row: HumanOutcomeRow) -> HumanOutcome:
    """Rebuild the domain outcome from its stored row."""
    return HumanOutcome.model_validate(
        {
            "id": row.id,
            "reviewer_display": row.reviewer_display,
            "created_at": row.created_at,
            "disposition": row.disposition,
            "response_type": row.response_type,
            "final_text": row.final_text,
            "reason_code": row.reason_code,
            "note": row.note,
            "run_id_seen": row.run_id_seen,
            "probe_corrections": row.probe_corrections,
        }
    )


@dataclass(frozen=True)
class DecisionRecord:
    """An outcome with the lane and band the reviewer saw (joined from the run they saw)."""

    outcome: HumanOutcome
    case_id: UUID
    changeset_id: int
    lane_at_decision: Lane
    band_at_decision: Band | None
    config_version: str
    decider_model: str | None


@dataclass(frozen=True)
class DecisionPage:
    """One page of the decision history and the cursor of the next page."""

    items: list[DecisionRecord]
    next_cursor: KeysetCursor | None


class OutcomesRepo:
    """Append outcomes; each append bumps the case version exactly once or fails."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(
        self,
        case_id: UUID,
        outcome: OutcomeInput,
        *,
        reviewer_display: str,
        session_id: UUID | None,
        expected_version: int,
        identity_id: UUID | None = None,
        now: datetime | None = None,
    ) -> HumanOutcome:
        """Record an outcome if `expected_version` is still current, else `VersionConflictError`.

        The version bump is the transaction's first write, so on SQLite a concurrent appender
        waits for the lock (busy_timeout) and then sees the new version and loses.
        """
        stamp = now or utcnow()
        changed = await rowcount(
            self._s,
            sa.update(ReviewCaseRow)
            .where(ReviewCaseRow.id == case_id, ReviewCaseRow.outcome_version == expected_version)
            .values(
                outcome_version=ReviewCaseRow.outcome_version + 1,
                status=CaseStatus.DECIDED.value,
                latest_outcome=outcome.disposition.value,
                updated_at=stamp,
            ),
        )
        if changed == 0:
            case = await self._s.get(ReviewCaseRow, case_id, populate_existing=True)
            if case is None:
                raise NotFoundError(f"case {case_id} does not exist")
            latest = await self.latest_for_case(case_id)
            raise VersionConflictError(
                expected=expected_version,
                current=case.outcome_version,
                current_outcome_id=None if latest is None else latest.id,
            )
        row = HumanOutcomeRow(
            id=uuid4(),
            case_id=case_id,
            run_id_seen=outcome.run_id_seen,
            session_id=session_id,
            reviewer_display=reviewer_display,
            disposition=outcome.disposition.value,
            response_type=None if outcome.response_type is None else outcome.response_type.value,
            final_text=outcome.final_text,
            reason_code=outcome.reason_code,
            note=outcome.note,
            probe_corrections=outcome.probe_corrections,
            identity_id=identity_id,
            created_at=stamp,
        )
        self._s.add(row)
        await self._s.flush()
        return outcome_to_model(row)

    async def latest_per_case(self) -> list[tuple[HumanOutcome, AnalysisRunRow]]:
        """Each case's newest outcome with the run its reviewer saw (a later outcome replaces an
        earlier one, so a changed mind is counted once). Outcomes whose run is gone are skipped."""
        newest = (
            sa.select(
                HumanOutcomeRow.case_id.label("case_id"),
                sa.func.max(HumanOutcomeRow.created_at).label("at"),
            )
            .group_by(HumanOutcomeRow.case_id)
            .subquery()
        )
        stmt = (
            sa.select(HumanOutcomeRow, AnalysisRunRow)
            .join(
                newest,
                sa.and_(
                    HumanOutcomeRow.case_id == newest.c.case_id,
                    HumanOutcomeRow.created_at == newest.c.at,
                ),
            )
            .join(AnalysisRunRow, AnalysisRunRow.id == HumanOutcomeRow.run_id_seen)
            .order_by(HumanOutcomeRow.created_at, HumanOutcomeRow.id)
        )
        result = await self._s.execute(stmt)
        return [(outcome_to_model(outcome), run) for outcome, run in result.all()]

    async def current_version(self, case_id: UUID) -> int:
        """The case's current outcome version (the value an `If-Match` must carry)."""
        result = await self._s.execute(
            sa.select(ReviewCaseRow.outcome_version).where(ReviewCaseRow.id == case_id)
        )
        version = result.scalars().first()
        if version is None:
            raise NotFoundError(f"case {case_id} does not exist")
        return int(version)

    async def latest_for_case(self, case_id: UUID) -> HumanOutcome | None:
        """Newest outcome of the case."""
        result = await self._s.execute(
            sa.select(HumanOutcomeRow)
            .where(HumanOutcomeRow.case_id == case_id)
            .order_by(HumanOutcomeRow.created_at.desc(), HumanOutcomeRow.id)
            .limit(1)
        )
        row = result.scalars().first()
        return None if row is None else outcome_to_model(row)

    async def list_for_case(self, case_id: UUID) -> list[HumanOutcome]:
        """Outcomes of the case, newest first."""
        result = await self._s.execute(
            sa.select(HumanOutcomeRow)
            .where(HumanOutcomeRow.case_id == case_id)
            .order_by(HumanOutcomeRow.created_at.desc(), HumanOutcomeRow.id)
        )
        return [outcome_to_model(r) for r in result.scalars()]

    async def list_decisions(
        self,
        cursor: KeysetCursor | None,
        limit: int,
        *,
        reviewer: str | None = None,
        disposition: Disposition | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> DecisionPage:
        """Decision history, newest first, keyset-paged on (created_at desc, id)."""
        o, r, c = HumanOutcomeRow, AnalysisRunRow, ReviewCaseRow
        stmt = (
            sa.select(o, r.lane, r.band, r.config_version, r.decider_model, c.changeset_id)
            .join(r, r.id == o.run_id_seen)
            .join(c, c.id == o.case_id)
        )
        if reviewer:
            stmt = stmt.where(o.reviewer_display == reviewer)
        if disposition is not None:
            stmt = stmt.where(o.disposition == disposition.value)
        if created_from is not None:
            stmt = stmt.where(o.created_at >= created_from)
        if created_to is not None:
            stmt = stmt.where(o.created_at <= created_to)
        if cursor is not None:
            stmt = stmt.where(
                sa.or_(
                    o.created_at < cursor.created_at,
                    sa.and_(o.created_at == cursor.created_at, o.id > cursor.id),
                )
            )
        stmt = stmt.order_by(o.created_at.desc(), o.id).limit(limit + 1)
        rows = (await self._s.execute(stmt)).all()
        next_cursor: KeysetCursor | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            tail = rows[-1][0]
            next_cursor = KeysetCursor(created_at=tail.created_at, id=tail.id)
        items = [
            DecisionRecord(
                outcome=outcome_to_model(out),
                case_id=out.case_id,
                changeset_id=int(changeset_id),
                lane_at_decision=Lane(lane),
                band_at_decision=None if band is None else Band(band),
                config_version=config_version,
                decider_model=decider_model,
            )
            for out, lane, band, config_version, decider_model, changeset_id in rows
        ]
        return DecisionPage(items=items, next_cursor=next_cursor)

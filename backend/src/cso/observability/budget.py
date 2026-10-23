"""Spend and volume guards: daily caps on analyses and drafts, and a Bedrock dollar ceiling.

Two different kinds of limit live here.

* **Counts** (analyses and draft requests per UTC day) are recomputed from the `jobs` table on
  every check, so they survive restarts and are shared by every process. The API checks them
  before queueing and answers 429 with code `daily_cap_reached`.
* **Bedrock dollars** are tracked by a `SpendLedger`. The drafting adapter records each call's
  estimated cost and asks `allow()` before the next one; once the cap is reached it must use the
  template draft instead. Draft jobs write their cost to `result_ref["bedrock_usd"]`, and
  `recompute_spend_from_jobs` rebuilds the day's total from those rows, so a restart does not
  reset the ceiling.

A cap of 0 means NOTHING is allowed (fail closed: an empty or mistyped value must not switch
protection off). A negative cap is the explicit, documented way to disable a limit.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from cso.api.db import SessionFactoryDep, SettingsDep
from cso.api.problems import ApiError
from cso.domain.enums import JobKind
from cso.observability.metrics import BUDGET_REJECTIONS, METRICS
from cso.persistence.tables import JobRow
from cso.settings import Settings, get_settings

Clock = Callable[[], datetime]
BEDROCK_USD_KEY = "bedrock_usd"


class DailyCapError(ApiError):
    """A daily volume cap is used up (429); `Retry-After` is the time until the next UTC day."""

    status = 429
    code = "daily_cap_reached"


class BedrockBudgetExhausted(Exception):
    """The Bedrock dollar ceiling for today is reached; the caller must use the template draft."""

    failure_code = "bedrock_budget_exhausted"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def utc_day_start(now: datetime) -> datetime:
    """Midnight UTC at the start of `now`'s day."""
    moment = now.astimezone(UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_until_next_day(now: datetime) -> int:
    """Whole seconds until the next UTC midnight (at least 1)."""
    nxt = utc_day_start(now) + timedelta(days=1)
    return max(1, int((nxt - now.astimezone(UTC)).total_seconds()))


async def count_jobs_today(session: AsyncSession, kind: JobKind, now: datetime) -> int:
    """Jobs of one kind created since the start of the UTC day (any status)."""
    since = utc_day_start(now)
    stmt = (
        sa.select(sa.func.count())
        .select_from(JobRow)
        .where(JobRow.kind == kind.value, JobRow.created_at >= since)
    )
    return int((await session.execute(stmt)).scalar_one())


class BudgetGuard:
    """Daily count caps from the settings, checked against the jobs table."""

    def __init__(self, settings: Settings, *, clock: Clock = _utc_now) -> None:
        self._caps = {
            JobKind.ANALYZE: settings.daily_analysis_cap,
            JobKind.DRAFT: settings.daily_draft_cap,
        }
        self._clock = clock

    async def check(self, session: AsyncSession, kind: JobKind, count: int = 1) -> None:
        """Raise `DailyCapError` unless `count` more jobs of this kind fit under today's cap.

        A cap of 0 refuses everything; a negative cap is unlimited.
        """
        cap = self._caps[kind]
        if cap < 0:
            return
        now = self._clock()
        used = await count_jobs_today(session, kind, now) if cap > 0 else 0
        if cap == 0 or used + max(1, count) > cap:
            METRICS.inc(BUDGET_REJECTIONS, cap=kind.value)
            raise DailyCapError(
                "Today's limit for this kind of request is used up; try again tomorrow (UTC).",
                headers={"Retry-After": str(seconds_until_next_day(now))},
                cap=kind.value,
                limit=cap,
            )


class SpendLedger:
    """Today's estimated Bedrock spend against a dollar ceiling (resets at UTC midnight)."""

    def __init__(self, cap_usd: float, *, clock: Clock = _utc_now) -> None:
        self.cap_usd = cap_usd
        self._clock = clock
        self._day = utc_day_start(clock())
        self._spent = 0.0

    def _roll(self) -> None:
        today = utc_day_start(self._clock())
        if today != self._day:
            self._day, self._spent = today, 0.0

    def record(self, usd: float) -> None:
        """Add one call's estimated cost."""
        self._roll()
        self._spent += max(0.0, usd)

    def hydrate(self, usd: float) -> None:
        """Raise today's total to at least `usd` (a total rebuilt from the database)."""
        self._roll()
        self._spent = max(self._spent, usd)

    def spent(self) -> float:
        """Estimated spend so far today."""
        self._roll()
        return self._spent

    def allow(self) -> bool:
        """True while a further Bedrock call fits under the ceiling.

        A ceiling of 0 allows no call (templates only); a negative ceiling is the explicit way to
        disable the limit.
        """
        return self.cap_usd < 0 or self.spent() < self.cap_usd

    def require(self) -> None:
        """Raise `BedrockBudgetExhausted` when the ceiling is reached."""
        if not self.allow():
            METRICS.inc(BUDGET_REJECTIONS, cap="bedrock_usd")
            raise BedrockBudgetExhausted(f"daily Bedrock ceiling of ${self.cap_usd:.2f} reached")


async def recompute_spend_from_jobs(session: AsyncSession, now: datetime) -> float:
    """Sum `result_ref["bedrock_usd"]` over draft jobs updated since the UTC day began."""
    since = utc_day_start(now)
    stmt = sa.select(JobRow.result_ref).where(
        JobRow.kind == JobKind.DRAFT.value, JobRow.updated_at >= since
    )
    total = 0.0
    for (ref,) in (await session.execute(stmt)).all():
        value = ref.get(BEDROCK_USD_KEY) if isinstance(ref, dict) else None
        if isinstance(value, (int, float)) and value > 0:
            total += float(value)
    return total


_ledger: SpendLedger | None = None


def spend_ledger() -> SpendLedger:
    """The process-wide ledger, created from `CSO_BEDROCK_DAILY_USD_CAP` on first use."""
    global _ledger
    if _ledger is None:
        _ledger = SpendLedger(get_settings().bedrock_daily_usd_cap)
    return _ledger


def reset_spend_ledger(ledger: SpendLedger | None = None) -> None:
    """Replace or clear the process-wide ledger (tests)."""
    global _ledger
    _ledger = ledger


# ------------------------------------------------------------------ FastAPI dependencies


async def analysis_cap(factory: SessionFactoryDep, settings: SettingsDep) -> None:
    """Dependency: refuse to queue an analysis once today's cap is used up."""
    async with factory() as session:
        await BudgetGuard(settings).check(session, JobKind.ANALYZE)


async def draft_cap(factory: SessionFactoryDep, settings: SettingsDep) -> None:
    """Dependency: refuse to queue a draft once today's cap is used up."""
    async with factory() as session:
        await BudgetGuard(settings).check(session, JobKind.DRAFT)


AnalysisCap = Depends(analysis_cap)
DraftCap = Depends(draft_cap)

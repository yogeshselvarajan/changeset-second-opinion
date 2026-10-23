"""Budget guard: daily caps from the jobs table, the Bedrock dollar ceiling, the 429 at the API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cso.api.db import app_settings
from cso.domain.enums import JobKind
from cso.jobs import enqueue_changeset
from cso.observability.budget import (
    BEDROCK_USD_KEY,
    BedrockBudgetExhausted,
    BudgetGuard,
    DailyCapError,
    SpendLedger,
    count_jobs_today,
    recompute_spend_from_jobs,
    reset_spend_ledger,
    seconds_until_next_day,
    spend_ledger,
    utc_day_start,
)
from cso.observability.metrics import BUDGET_REJECTIONS, METRICS
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, JobsRepo
from cso.settings import Settings

NOON = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


async def queue_analyses(factory, n: int, *, when: datetime = NOON) -> None:
    async with session_scope(factory) as session:
        for i in range(n):
            await enqueue_changeset(session, 900000000100 + i, now=when)


# --------------------------------------------------------------------------- day arithmetic


def test_day_start_and_time_to_next_day() -> None:
    assert utc_day_start(NOON) == datetime(2026, 10, 17, tzinfo=UTC)
    assert seconds_until_next_day(NOON) == 12 * 3600
    late = datetime(2026, 10, 17, 23, 59, 59, 500000, tzinfo=UTC)
    assert seconds_until_next_day(late) == 1


# --------------------------------------------------------------------------- count caps


async def test_the_cap_allows_jobs_until_it_is_reached(factory) -> None:
    guard = BudgetGuard(Settings(daily_analysis_cap=3), clock=FakeClock())
    await queue_analyses(factory, 2)
    async with factory() as session:
        await guard.check(session, JobKind.ANALYZE)  # 2 < 3: fine
    await queue_analyses(factory, 3)  # ids overlap, so only one new job (900000000102)
    async with factory() as session:
        assert await count_jobs_today(session, JobKind.ANALYZE, NOON) == 3
        with pytest.raises(DailyCapError) as caught:
            await guard.check(session, JobKind.ANALYZE)
    error = caught.value
    assert error.status == 429 and error.code == "daily_cap_reached"
    assert error.headers["Retry-After"] == str(12 * 3600)
    assert error.extensions == {"cap": "analyze", "limit": 3}
    assert METRICS.counter(BUDGET_REJECTIONS, cap="analyze") == 1


async def test_a_cap_of_zero_allows_nothing_and_a_negative_cap_disables_the_limit(factory) -> None:
    zero = BudgetGuard(Settings(daily_analysis_cap=0, daily_draft_cap=0), clock=FakeClock())
    async with factory() as session:
        with pytest.raises(DailyCapError):
            await zero.check(session, JobKind.ANALYZE)
        with pytest.raises(DailyCapError):
            await zero.check(session, JobKind.DRAFT)
    off = BudgetGuard(Settings(daily_analysis_cap=-1, daily_draft_cap=-1), clock=FakeClock())
    await queue_analyses(factory, 4)
    async with factory() as session:
        await off.check(session, JobKind.ANALYZE)
        await off.check(session, JobKind.DRAFT)


async def test_a_batch_that_does_not_fit_under_the_remaining_cap_is_refused(factory) -> None:
    guard = BudgetGuard(Settings(daily_analysis_cap=3), clock=FakeClock())
    await queue_analyses(factory, 2)
    async with factory() as session:
        await guard.check(session, JobKind.ANALYZE, count=1)
        with pytest.raises(DailyCapError):
            await guard.check(session, JobKind.ANALYZE, count=2)


async def test_jobs_from_yesterday_do_not_count_after_midnight(factory) -> None:
    clock = FakeClock()
    guard = BudgetGuard(Settings(daily_analysis_cap=2), clock=clock)
    await queue_analyses(factory, 2, when=NOON)
    async with factory() as session:
        with pytest.raises(DailyCapError):
            await guard.check(session, JobKind.ANALYZE)
    clock.advance(hours=13)  # 01:00 the next day
    async with factory() as session:
        await guard.check(session, JobKind.ANALYZE)
        assert await count_jobs_today(session, JobKind.ANALYZE, clock()) == 0


async def test_analysis_and_draft_caps_are_independent(factory) -> None:
    guard = BudgetGuard(Settings(daily_analysis_cap=1, daily_draft_cap=1), clock=FakeClock())
    await queue_analyses(factory, 1)
    async with factory() as session:
        with pytest.raises(DailyCapError):
            await guard.check(session, JobKind.ANALYZE)
        await guard.check(session, JobKind.DRAFT)  # no drafts yet


async def test_counts_come_from_the_database_so_a_restart_changes_nothing(factory) -> None:
    await queue_analyses(factory, 2)
    first = BudgetGuard(Settings(daily_analysis_cap=2), clock=FakeClock())
    second = BudgetGuard(Settings(daily_analysis_cap=2), clock=FakeClock())  # "after a restart"
    for guard in (first, second):
        async with factory() as session:
            with pytest.raises(DailyCapError):
                await guard.check(session, JobKind.ANALYZE)


# --------------------------------------------------------------------------- Bedrock ceiling


def test_ledger_allows_spend_until_the_ceiling_then_refuses() -> None:
    clock = FakeClock()
    ledger = SpendLedger(1.00, clock=clock)
    assert ledger.allow() and ledger.spent() == 0
    ledger.record(0.40)
    ledger.record(0.40)
    assert ledger.allow() and ledger.spent() == pytest.approx(0.80)
    ledger.record(0.30)  # 1.10 >= 1.00: the next call must use the template
    assert not ledger.allow()
    with pytest.raises(BedrockBudgetExhausted) as caught:
        ledger.require()
    assert caught.value.failure_code == "bedrock_budget_exhausted"
    assert METRICS.counter(BUDGET_REJECTIONS, cap="bedrock_usd") == 1


def test_ledger_resets_at_utc_midnight_with_a_fake_clock() -> None:
    clock = FakeClock(datetime(2026, 10, 17, 23, 30, tzinfo=UTC))
    ledger = SpendLedger(0.50, clock=clock)
    ledger.record(0.60)
    assert not ledger.allow()
    clock.advance(minutes=45)  # 00:15 the next day
    assert ledger.allow() and ledger.spent() == 0


def test_ledger_with_a_zero_cap_allows_no_call_and_a_negative_cap_disables_it() -> None:
    ledger = SpendLedger(0.0, clock=FakeClock())
    assert not ledger.allow()
    with pytest.raises(BedrockBudgetExhausted):
        ledger.require()
    off = SpendLedger(-1.0, clock=FakeClock())
    off.record(1000.0)
    assert off.allow()


def test_negative_costs_are_ignored_and_hydrate_only_raises_the_total() -> None:
    ledger = SpendLedger(10.0, clock=FakeClock())
    ledger.record(-5.0)
    assert ledger.spent() == 0
    ledger.hydrate(3.0)
    ledger.hydrate(1.0)  # lower than what is known: ignored
    assert ledger.spent() == 3.0


async def test_spend_is_rebuilt_from_draft_job_rows_after_a_restart(factory) -> None:
    clock = FakeClock()
    async with session_scope(factory) as session:
        cases = CasesRepo(session)
        jobs = JobsRepo(session)
        case, _ = await cases.get_or_create(900000000201, now=NOON)
        run_id = uuid4()
        for i, usd in enumerate([0.02, 0.03, None, -1.0]):
            job, _ = await jobs.enqueue(
                case.id, JobKind.DRAFT, evidence_version=f"gen-{i}", run_id=run_id, now=NOON
            )
            job.result_ref = {BEDROCK_USD_KEY: usd} if usd is not None else {"other": 1}
        # a draft from yesterday must not count today
        old, _ = await jobs.enqueue(
            case.id, JobKind.DRAFT, evidence_version="old", run_id=run_id, now=NOON
        )
        old.result_ref = {BEDROCK_USD_KEY: 5.0}
        old.updated_at = NOON - timedelta(days=1)
    async with factory() as session:
        total = await recompute_spend_from_jobs(session, clock())
    assert total == pytest.approx(0.05)

    ledger = SpendLedger(0.04, clock=clock)  # a fresh process: nothing recorded in memory
    assert ledger.allow()
    ledger.hydrate(total)
    assert not ledger.allow()


def test_the_process_ledger_follows_the_settings_cap(monkeypatch) -> None:
    from cso.settings import get_settings

    monkeypatch.setenv("CSO_BEDROCK_DAILY_USD_CAP", "2.5")
    get_settings.cache_clear()
    reset_spend_ledger(None)
    try:
        assert spend_ledger().cap_usd == 2.5
        assert spend_ledger() is spend_ledger()
    finally:
        reset_spend_ledger(None)
        get_settings.cache_clear()


def test_default_caps_are_safe_values() -> None:
    settings = Settings()
    assert settings.bedrock_daily_usd_cap == 10.0
    assert settings.daily_analysis_cap == 200 and settings.daily_draft_cap == 100


# --------------------------------------------------------------------------- at the API


async def test_post_cases_returns_429_problem_once_the_daily_cap_is_used_up(app, client) -> None:
    app.dependency_overrides[app_settings] = lambda: Settings(daily_analysis_cap=1)
    first = await client.post("/api/v1/cases", json={"changeset_id": 900000000001})
    assert first.status_code == 201
    second = await client.post("/api/v1/cases", json={"changeset_id": 900000000002})
    assert second.status_code == 429
    body = second.json()
    assert second.headers["content-type"].startswith("application/problem+json")
    assert body["type"].endswith("daily_cap_reached") and body["request_id"]
    assert body["cap"] == "analyze" and body["limit"] == 1
    assert int(second.headers["retry-after"]) >= 1


async def test_a_zero_cap_refuses_and_a_negative_cap_lets_requests_through_at_the_api(
    app, client
) -> None:
    app.dependency_overrides[app_settings] = lambda: Settings(daily_analysis_cap=0)
    refused = await client.post("/api/v1/cases", json={"changeset_id": 900000000009})
    assert refused.status_code == 429
    app.dependency_overrides[app_settings] = lambda: Settings(daily_analysis_cap=-1)
    for n in (1, 2, 3):
        response = await client.post("/api/v1/cases", json={"changeset_id": 900000000000 + n})
        assert response.status_code == 201

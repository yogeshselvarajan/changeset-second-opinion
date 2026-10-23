"""Bedrock dollars in the draft job: ceiling, result_ref, restart, counters and the client guard."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from jobs_support import (
    Factory,
    FakePanelDecider,
    ManualClock,
    config,
    get_job,
    make_deps,
)
from test_jobs_draft_handler import analyse, drafts_of, request_draft

from cso.adapters.bedrock import BedrockUnavailable, DraftBudget, FakeDrafter
from cso.adapters.bedrock import client as bedrock_client
from cso.domain.enums import DraftStatus, JobStatus
from cso.jobs import Deps, Worker
from cso.jobs.deps import DraftingDeps, build_drafting_deps
from cso.jobs.spend import LedgerSpend
from cso.observability.budget import SpendLedger
from cso.observability.metrics import (
    BEDROCK_CALLS,
    BEDROCK_TOKENS,
    BUDGET_REJECTIONS,
    METRICS,
    TEMPLATE_FALLBACKS,
)
from cso.persistence.db import session_scope
from cso.settings import Settings

MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
ONE_CALL_USD = (900 * 1.0 + 120 * 5.0) / 1_000_000  # FakeDrafter: 900 input and 120 output tokens


@pytest.fixture(autouse=True)
def fresh_metrics() -> None:
    METRICS.reset()


def spend_deps(
    drafter: FakeDrafter, ledger: SpendLedger, *, budget: DraftBudget | None = None
) -> Deps:
    deps = make_deps(FakePanelDecider(config()[0]))
    deps.drafting = DraftingDeps(drafter=drafter, budget=budget, spend=LedgerSpend(ledger))
    return deps


async def draft_once(
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
    deps: Deps,
    fixture: int,
) -> tuple[Any, Any]:
    """Analyse a fixture, request its (always allowed) source question, return (job, draft row)."""
    case_id, run_id = await analyse(factory, clock, make_worker, fixture, deps=deps)
    job_id = await request_draft(factory, clock, case_id, run_id, "ask_source_question")
    await make_worker(deps=deps).run_until_idle()
    (row,) = await drafts_of(factory, case_id)
    return await get_job(factory, job_id), row


# ----------------------------------------------------------------------------- a model call


async def test_a_model_draft_writes_calls_tokens_and_dollars_to_the_job_and_the_ledger(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    ledger = SpendLedger(cap_usd=10.0)
    deps = spend_deps(FakeDrafter(model_id=MODEL), ledger)
    job, row = await draft_once(factory, clock, make_worker, deps, 5)

    assert job.status == JobStatus.SUCCEEDED.value and row.status == DraftStatus.VALIDATED.value
    assert job.result_ref == {
        "draft_id": str(row.id),
        "status": "validated",
        "model_calls": 1,
        "input_tokens": 900,
        "output_tokens": 120,
        "bedrock_usd": pytest.approx(ONE_CALL_USD),
    }
    assert ledger.spent() == pytest.approx(ONE_CALL_USD)


async def test_the_counters_are_bumped_for_a_call_and_not_for_a_fallback(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    deps = spend_deps(FakeDrafter(model_id=MODEL), SpendLedger(10.0))
    await draft_once(factory, clock, make_worker, deps, 5)
    assert METRICS.counter(BEDROCK_CALLS, outcome="ok") == 1
    assert METRICS.counter(BEDROCK_TOKENS, direction="input") == 900
    assert METRICS.counter(BEDROCK_TOKENS, direction="output") == 120
    assert METRICS.total(TEMPLATE_FALLBACKS) == 0
    assert METRICS.counter(BEDROCK_CALLS, outcome="error") == 0


async def test_a_failed_bedrock_call_counts_as_an_error_and_a_template_fallback(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    ledger = SpendLedger(cap_usd=10.0)
    deps = spend_deps(FakeDrafter(error=BedrockUnavailable("throttled")), ledger)
    job, row = await draft_once(factory, clock, make_worker, deps, 5)
    assert row.status == DraftStatus.TEMPLATE_FALLBACK.value
    assert row.usage["fallback_reason"] == "bedrock_unavailable"
    assert METRICS.counter(BEDROCK_CALLS, outcome="error") == 1
    assert METRICS.counter(TEMPLATE_FALLBACKS, reason="bedrock_unavailable") == 1
    assert "bedrock_usd" not in job.result_ref and ledger.spent() == 0.0  # nothing was spent


# ----------------------------------------------------------------------------- the ceiling


async def test_at_the_ceiling_the_draft_is_a_template_and_no_call_or_client_is_made(
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def refuse(name: str) -> Any:
        requested.append(name)
        raise AssertionError(f"the budget-stopped path tried to load {name}")

    monkeypatch.setattr(bedrock_client, "importlib", SimpleNamespace(import_module=refuse))
    ledger = SpendLedger(cap_usd=0.001)
    ledger.record(0.002)  # already over today's ceiling
    drafter = FakeDrafter()
    job, row = await draft_once(factory, clock, make_worker, spend_deps(drafter, ledger), 5)

    assert job.status == JobStatus.SUCCEEDED.value  # the draft is never lost to the ceiling
    assert row.status == DraftStatus.TEMPLATE_FALLBACK.value and row.model_id is None
    assert row.usage["fallback_reason"] == "budget_exceeded" and row.usage["model_calls"] == 0
    assert drafter.calls == 0 and requested == []
    assert job.result_ref == {"draft_id": str(row.id), "status": "template_fallback"}
    assert METRICS.counter(TEMPLATE_FALLBACKS, reason="budget_exceeded") == 1
    assert METRICS.total(BEDROCK_CALLS) == 0
    assert METRICS.counter(BUDGET_REJECTIONS, cap="bedrock_usd") >= 1


async def test_the_ceiling_survives_a_restart_because_it_is_rebuilt_from_the_jobs(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    cap = 0.8 * ONE_CALL_USD  # the first call fits (spent 0 < cap); after it the day is over
    before_restart = SpendLedger(cap_usd=cap)
    first_job, first = await draft_once(
        factory, clock, make_worker, spend_deps(FakeDrafter(model_id=MODEL), before_restart), 5
    )
    assert first.status == DraftStatus.VALIDATED.value
    assert first_job.result_ref["bedrock_usd"] == pytest.approx(ONE_CALL_USD)

    # A restart: a brand-new ledger knows nothing, and would allow a call on its own.
    after_restart = SpendLedger(cap_usd=cap)
    assert after_restart.allow() and after_restart.spent() == 0.0
    drafter = FakeDrafter(model_id=MODEL)
    second_job, second = await draft_once(
        factory, clock, make_worker, spend_deps(drafter, after_restart), 3
    )

    assert second_job.status == JobStatus.SUCCEEDED.value
    assert second.status == DraftStatus.TEMPLATE_FALLBACK.value
    assert second.usage["fallback_reason"] == "budget_exceeded" and drafter.calls == 0
    assert after_restart.spent() == pytest.approx(ONE_CALL_USD)  # hydrated, not summed twice


async def test_hydration_never_lowers_the_ledger_and_is_the_larger_of_the_two_totals(
    factory: Factory, clock: ManualClock
) -> None:
    ledger = SpendLedger(cap_usd=100.0)
    ledger.record(5.0)
    spend = LedgerSpend(ledger)
    async with session_scope(factory) as session:
        assert await spend.hydrate(session, clock()) == 0.0  # the database knows no spend yet
    assert ledger.spent() == pytest.approx(5.0)


async def test_the_burst_limiter_does_not_add_to_the_dollar_total(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    ledger = SpendLedger(cap_usd=10.0)
    drafter = FakeDrafter(model_id=MODEL)
    deps = spend_deps(drafter, ledger, budget=DraftBudget(max_calls=1))
    _, first = await draft_once(factory, clock, make_worker, deps, 5)
    _, second = await draft_once(factory, clock, make_worker, deps, 3)

    assert first.status == DraftStatus.VALIDATED.value
    assert second.usage["fallback_reason"] == "budget_exceeded"  # the burst limiter stopped it
    assert drafter.calls == 1 and ledger.spent() == pytest.approx(ONE_CALL_USD)  # counted once


# ----------------------------------------------------------------------------- wiring and guard


def test_price_overrides_from_the_settings_change_the_recorded_cost() -> None:
    ledger = SpendLedger(cap_usd=100.0)
    spend = LedgerSpend.from_settings(
        Settings(bedrock_input_usd_per_mtok=2.0, bedrock_output_usd_per_mtok=10.0), ledger
    )
    assert spend.record(MODEL, 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert ledger.spent() == pytest.approx(12.0)


@pytest.mark.parametrize(
    "settings",
    [
        Settings(mode="replay"),
        Settings(mode="live", user_agent="CSOTest/1 (+https://example.org/repo; test@example.org)"),
    ],
    ids=["replay", "live-without-the-flag"],
)
def test_wiring_the_spend_gate_never_creates_a_bedrock_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested: list[str] = []

    def refuse(name: str) -> Any:
        requested.append(name)
        raise AssertionError(f"building the drafting deps tried to load {name}")

    monkeypatch.setattr(bedrock_client, "importlib", SimpleNamespace(import_module=refuse))
    monkeypatch.delenv("CSO_LIVE_BEDROCK", raising=False)
    deps = build_drafting_deps(settings)
    assert deps.drafter is None and deps.spend is not None and requested == []


# ------------------------------------------------- review F-L12 and F-L13 (failure paths)


async def test_a_run_of_another_case_is_refused_and_a_newer_run_at_store_time_is_refused(
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from jobs_support import enqueue_fixture

    from cso.domain.enums import JobKind
    from cso.persistence.repos import JobsRepo, RunsRepo

    deps = spend_deps(FakeDrafter(model_id=MODEL), SpendLedger(10.0))
    case_a, run_a = await analyse(factory, clock, make_worker, 5, deps=deps)
    case_b, _ = await enqueue_fixture(factory, 2, clock)
    await make_worker(deps=deps).run_until_idle()
    async with session_scope(factory) as session:
        job, _ = await JobsRepo(session).enqueue(
            case_b,
            JobKind.DRAFT,
            run_id=run_a,
            response_type="ask_source_question",
            now=clock(),
        )
    await make_worker(deps=deps).run_until_idle()
    refused = await get_job(factory, job.id)
    assert refused.status == JobStatus.FAILED.value
    assert refused.last_error == "draft_run_mismatch"
    assert await drafts_of(factory, case_b) == []

    # A newer analysis that appears after the load check is caught in the storing transaction.
    real = RunsRepo.latest_for_case
    calls = {"n": 0}

    async def racing(self: Any, case_id: Any) -> Any:
        calls["n"] += 1
        if calls["n"] >= 2:
            return SimpleNamespace(id=uuid4())
        return await real(self, case_id)

    monkeypatch.setattr(RunsRepo, "latest_for_case", racing)
    job_id = await request_draft(factory, clock, case_a, run_a, "ask_source_question")
    await make_worker(deps=deps).run_until_idle()
    stale = await get_job(factory, job_id)
    assert stale.status == JobStatus.FAILED.value and stale.last_error == "draft_run_stale"
    assert await drafts_of(factory, case_a) == []


async def test_spend_of_a_job_that_fails_after_a_model_call_is_kept_and_rebuilt(
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from cso.observability.budget import recompute_spend_from_jobs
    from cso.persistence.repos import RunsRepo

    ledger = SpendLedger(10.0)
    deps = spend_deps(FakeDrafter(model_id=MODEL), ledger)
    case_id, run_id = await analyse(factory, clock, make_worker, 5, deps=deps)
    real = RunsRepo.latest_for_case
    calls = {"n": 0}

    async def racing(self: Any, case: Any) -> Any:
        calls["n"] += 1
        return SimpleNamespace(id=uuid4()) if calls["n"] >= 2 else await real(self, case)

    monkeypatch.setattr(RunsRepo, "latest_for_case", racing)
    job_id = await request_draft(factory, clock, case_id, run_id, "ask_source_question")
    await make_worker(deps=deps).run_until_idle()
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.result_ref["bedrock_usd"] == pytest.approx(ONE_CALL_USD)
    async with session_scope(factory) as session:
        assert await recompute_spend_from_jobs(session, clock()) == pytest.approx(ONE_CALL_USD)

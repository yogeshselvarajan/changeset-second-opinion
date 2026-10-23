"""Crash and resume: no duplicate snapshots, atomic run + case + job commit, force re-analysis."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from jobs_support import (
    FIXTURES,
    CountingProvider,
    FakePanelDecider,
    ManualClock,
    audit_actions,
    config,
    enqueue_fixture,
    get_case,
    get_job,
    make_deps,
    runs_of,
    snapshot_count,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import CaseStatus, JobStatus, RunStatus
from cso.jobs import Worker, enqueue_analysis
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo

Factory = async_sessionmaker[AsyncSession]


async def test_a_crash_after_the_snapshot_step_resumes_without_duplicates(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    provider = CountingProvider(FIXTURES)
    decider = FakePanelDecider(config()[0], failures=[RuntimeError("process died in decide")])
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(deps=make_deps(decider, provider))

    await worker.run_until_idle()  # attempt 1: evidence stored, then the crash
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.QUEUED.value and job.attempts == 1
    assert job.result_ref is not None and "snapshot_id" in job.result_ref  # progress was saved
    assert await snapshot_count(factory, case_id) == 1
    assert await runs_of(factory, case_id) == []

    clock.advance(5)
    await worker.run_until_idle()  # attempt 2 resumes at `decide`

    job = await get_job(factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value and job.attempts == 2
    assert provider.lookups == 1  # evidence was fetched once, not again on the retry
    assert await snapshot_count(factory, case_id) == 1
    (run,) = await runs_of(factory, case_id)
    assert run.snapshot_id == (await get_case(factory, case_id)).latest_snapshot_id


async def test_run_case_pointer_audit_and_job_state_commit_together(
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_id, job_id = await enqueue_fixture(factory, 2, clock)
    real_append = AuditRepo.append
    failing = {"on": True}

    async def flaky_append(self: AuditRepo, **kwargs: object) -> object:
        if failing["on"] and kwargs.get("action") == "analysis.completed":
            raise RuntimeError("disk full while writing the audit event")
        return await real_append(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(AuditRepo, "append", flaky_append)
    worker = make_worker()

    await worker.run_until_idle()

    assert await runs_of(factory, case_id) == []  # nothing from the failed transaction survived
    case = await get_case(factory, case_id)
    assert case.latest_run_id is None and case.band is None and case.response is None
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.QUEUED.value and job.last_error == "internal_error"

    failing["on"] = False
    clock.advance(5)
    await worker.run_until_idle()

    (run,) = await runs_of(factory, case_id)  # exactly one run after the retry
    assert (await get_job(factory, job_id)).status == JobStatus.SUCCEEDED.value
    assert (await get_case(factory, case_id)).latest_run_id == run.id
    assert await snapshot_count(factory, case_id) == 1


async def test_forced_reanalysis_adds_a_run_but_not_a_duplicate_snapshot(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, first_job = await enqueue_fixture(factory, 2, clock)
    worker = make_worker()
    await worker.run_until_idle()

    async with session_scope(factory) as session:
        second_job, created = await enqueue_analysis(session, case_id, force=True, now=clock())
    assert created
    await worker.run_until_idle()

    runs = await runs_of(factory, case_id)
    assert len(runs) == 2 and all(r.status == RunStatus.SUCCEEDED.value for r in runs)
    assert await snapshot_count(factory, case_id) == 1  # same evidence version, stored once
    case = await get_case(factory, case_id)
    second = await get_job(factory, second_job.id)
    assert second.status == JobStatus.SUCCEEDED.value and second.result_ref is not None
    assert str(case.latest_run_id) == second.result_ref["run_id"]  # the case points at the newest
    assert case.status == CaseStatus.ANALYZED.value
    assert (await get_job(factory, first_job)).status == JobStatus.SUCCEEDED.value
    assert (await audit_actions(factory, case_id)).count("analysis.completed") == 2

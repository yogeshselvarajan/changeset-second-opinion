"""End-to-end analysis of replay fixtures through the worker, a fake Decider and a real database."""

from __future__ import annotations

import socket
from collections.abc import Callable

import pytest
from jobs_support import (
    CASES,
    FakePanelDecider,
    ManualClock,
    audit_actions,
    config,
    enqueue_fixture,
    get_case,
    get_job,
    make_panel,
    runs_of,
    snapshot_count,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.adapters.osm import ReplayClient, collect
from cso.domain.enums import CaseStatus, JobStatus, Lane, RunStatus
from cso.domain.evidence import render
from cso.domain.lanes import evaluate_panel_run
from cso.jobs import Worker
from cso.persistence.db import session_scope
from cso.persistence.repos import RunsRepo, SnapshotsRepo

Factory = async_sessionmaker[AsyncSession]


async def _expected_lane(number: int, decider: FakePanelDecider) -> Lane:
    """What the policy gate says for this fixture and the fake Decider's panel."""
    cfg = config()[0]
    case_dir = next(CASES.glob(f"{number:02d}-*"))
    snapshot = await collect(ReplayClient(case_dir), ReplayClient(case_dir).case.changeset.id)
    return evaluate_panel_run(snapshot, make_panel(cfg), cfg).lane


@pytest.mark.parametrize("number", [1, 2, 4, 6, 7])
async def test_replay_analysis_stores_snapshot_run_and_case_pointers(
    number: int,
    factory: Factory,
    clock: ManualClock,
    decider: FakePanelDecider,
    make_worker: Callable[..., Worker],
) -> None:
    case_id, job_id = await enqueue_fixture(factory, number, clock)

    outcomes = await make_worker().run_until_idle()

    assert [o.status for o in outcomes] == [JobStatus.SUCCEEDED]
    job = await get_job(factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value and job.attempts == 1
    assert job.last_error is None and job.locked_by is None

    runs = await runs_of(factory, case_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == RunStatus.SUCCEEDED.value
    assert run.job_id == job_id
    assert run.lane == (await _expected_lane(number, decider)).value
    assert run.config_version == config()[0].version
    assert job.result_ref is not None and job.result_ref["run_id"] == str(run.id)

    receipt = run.receipt
    assert receipt is not None
    assert receipt["decider"]["model"] == "fake-decider"
    assert receipt["panel"]["advisory_nature"]["advisory"] is True
    assert receipt["panel_questions_hash"] == "qh-test"
    assert receipt["lane"] == run.lane
    assert {"fetch", "snapshot", "decide", "total"} <= set(receipt["timing_ms"])

    case = await get_case(factory, case_id)
    assert case.latest_run_id == run.id and case.lane == run.lane
    assert case.status == CaseStatus.ANALYZED.value
    assert case.latest_snapshot_id == run.snapshot_id
    assert await snapshot_count(factory, case_id) == 1
    assert await audit_actions(factory, case_id) == ["job.enqueued", "analysis.completed"]


async def test_fixture_02_gets_a_lane_and_a_receipt(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    await make_worker().run_until_idle()

    async with session_scope(factory) as session:
        result = await RunsRepo(session).latest_for_case(case_id)
    assert result is not None and result.status is RunStatus.SUCCEEDED
    assert result.lane is not Lane.RULES_ONLY


@pytest.mark.parametrize("number", [4, 6])
async def test_thin_coverage_forces_insufficient_evidence_whatever_the_panel_says(
    number: int, factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, _ = await enqueue_fixture(factory, number, clock)  # panel is fully reassuring
    await make_worker().run_until_idle()

    (run,) = await runs_of(factory, case_id)
    assert run.lane == Lane.INSUFFICIENT_EVIDENCE.value
    assert {"R3"} <= {hit["code"] for hit in run.rules_fired}


async def test_fixture_04_rule_r1_is_recorded_despite_a_reassuring_panel(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, _ = await enqueue_fixture(factory, 4, clock)
    await make_worker().run_until_idle()

    (run,) = await runs_of(factory, case_id)
    assert "R1" in {hit["code"] for hit in run.rules_fired}
    assert run.response != "no_action_suggested"


async def test_the_decider_gets_the_compact_rendering_of_the_stored_snapshot(
    factory: Factory,
    clock: ManualClock,
    decider: FakePanelDecider,
    make_worker: Callable[..., Worker],
) -> None:
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    await make_worker().run_until_idle()

    async with session_scope(factory) as session:
        snapshot = await SnapshotsRepo(session).latest_for_case(case_id)
    assert snapshot is not None and snapshot.rendered_text
    cfg = config()[0]
    compact = render(snapshot, cfg, profile="compact")
    assert decider.states == [compact.text]
    assert compact.estimated_tokens <= 1200
    assert snapshot.rendered_text == render(snapshot, cfg).text  # stored text is the full profile


async def test_replay_analysis_never_opens_a_socket(
    factory: Factory,
    clock: ManualClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay mode tried to open a network connection")

    await enqueue_fixture(factory, 2, clock)
    monkeypatch.setattr(socket.socket, "connect", refuse)

    outcomes = await make_worker().run_until_idle()

    assert [o.status for o in outcomes] == [JobStatus.SUCCEEDED]

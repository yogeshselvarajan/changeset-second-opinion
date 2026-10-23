"""A replay analysis is traceable: one request id from the API call through every worker step."""

from __future__ import annotations

from uuid import UUID

from jobs_support import FakePanelDecider, config, make_deps

from cso.adapters.decider.errors import DeciderSchemaError
from cso.jobs import Worker, enqueue_analysis, enqueue_changeset
from cso.jobs.states import ANALYZE_STEPS
from cso.observability.metrics import (
    ANALYSES,
    DECIDER_CALLS,
    DECIDER_LATENCY,
    JOB_FAILURES,
    METRICS,
)
from cso.persistence.db import session_scope
from cso.persistence.tables import JobRow


def make_worker(factory, decider: FakePanelDecider) -> Worker:
    return Worker(
        factory,
        make_deps(decider),
        poll_interval_s=0.01,
        reaper_interval_s=0.05,
        rng=lambda: 0.5,
        concurrency=1,
    )


async def job_row(factory, job_id: str | UUID) -> JobRow:
    async with factory() as session:
        row = await session.get(JobRow, UUID(str(job_id)), populate_existing=True)
    assert row is not None
    return row


async def test_request_id_flows_from_the_api_through_every_worker_step(
    client, factory, logs
) -> None:
    response = await client.post(
        "/api/v1/cases",
        json={"changeset_id": 900000000001},
        headers={"X-Request-ID": "trace-req-77"},
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    assert (await job_row(factory, job_id)).request_id == "trace-req-77"

    outcomes = await make_worker(factory, FakePanelDecider(config()[0])).run_until_idle()
    assert [o.status.value for o in outcomes] == ["succeeded"]

    lines = logs.lines()
    traced = [line for line in lines if line.get("request_id") == "trace-req-77"]
    events = {line["event"] for line in traced}
    assert {"http.request", "job.claimed", "job.step", "analysis.persisted"} <= events
    assert "job.attempt_done" in events
    (access,) = [e for e in traced if e["event"] == "http.request"]
    assert access["route"] == "/api/v1/cases" and access["method"] == "POST"

    worker_lines = [line for line in lines if line["event"].startswith(("job.", "analysis."))]
    assert worker_lines, "the worker wrote no log lines"
    assert {line["request_id"] for line in worker_lines} == {"trace-req-77"}
    assert {line["job_id"] for line in worker_lines} == {job_id}
    assert len({line["case_id"] for line in worker_lines}) == 1

    steps = [line["step"] for line in traced if line["event"] == "job.step"]
    for step in ANALYZE_STEPS[1:]:  # fetch is the claim itself; the later steps are checkpointed
        assert step in steps, f"no log line for step {step}"


async def test_unrelated_requests_keep_separate_ids(client, factory, logs) -> None:
    a = await client.post(
        "/api/v1/cases", json={"changeset_id": 900000000001}, headers={"X-Request-ID": "req-A"}
    )
    b = await client.post(
        "/api/v1/cases", json={"changeset_id": 900000000002}, headers={"X-Request-ID": "req-B"}
    )
    assert (await job_row(factory, a.json()["job_id"])).request_id == "req-A"
    assert (await job_row(factory, b.json()["job_id"])).request_id == "req-B"

    await make_worker(factory, FakePanelDecider(config()[0])).run_until_idle()
    claimed = {line["job_id"]: line["request_id"] for line in logs.events("job.claimed")}
    assert claimed == {a.json()["job_id"]: "req-A", b.json()["job_id"]: "req-B"}


async def test_a_job_queued_without_a_request_still_logs_its_job_and_case_ids(
    factory, logs
) -> None:
    async with session_scope(factory) as session:
        queued = await enqueue_changeset(session, 900000000002)
    assert queued.job.request_id is None

    await make_worker(factory, FakePanelDecider(config()[0])).run_until_idle()
    (claimed,) = logs.events("job.claimed")
    assert claimed["job_id"] == str(queued.job.id) and claimed["case_id"] == str(queued.case.id)
    assert "request_id" not in claimed


async def test_the_first_request_that_queues_a_job_is_the_one_recorded(factory) -> None:
    async with session_scope(factory) as session:
        first = await enqueue_changeset(session, 900000000001, request_id="first")
        job, created = await enqueue_analysis(session, first.case.id, request_id="second")
    assert not created and job.id == first.job.id and job.request_id == "first"


async def test_ids_do_not_leak_between_jobs_after_the_worker_finishes(factory, logs) -> None:
    from cso.observability import current_context

    async with session_scope(factory) as session:
        await enqueue_changeset(session, 900000000001, request_id="leaky")
    await make_worker(factory, FakePanelDecider(config()[0])).run_until_idle()
    assert current_context() == {}


async def test_analysis_counters_and_decider_latency_are_recorded(factory) -> None:
    async with session_scope(factory) as session:
        await enqueue_changeset(session, 900000000001)
    await make_worker(factory, FakePanelDecider(config()[0])).run_until_idle()
    assert METRICS.total(ANALYSES) == 1
    assert METRICS.counter(DECIDER_CALLS, outcome="ok") == 1
    assert METRICS.histogram_count(DECIDER_LATENCY) == 1
    assert METRICS.total(JOB_FAILURES) == 0


async def test_a_decider_failure_is_counted_by_code(factory) -> None:
    failing = FakePanelDecider(config()[0], failures=[DeciderSchemaError("bad shape", {})])
    async with session_scope(factory) as session:
        await enqueue_changeset(session, 900000000001)
    outcomes = await make_worker(factory, failing).run_until_idle()
    assert [o.status.value for o in outcomes] == ["failed"]
    code = outcomes[0].error
    assert code and METRICS.counter(DECIDER_CALLS, outcome=code) == 1
    assert METRICS.counter(JOB_FAILURES, kind="analyze", code=code) == 1
    assert (
        METRICS.counter(ANALYSES, lane="rules_only", status="failed")
        + METRICS.counter(ANALYSES, lane="insufficient_evidence", status="failed")
        >= 1
    )

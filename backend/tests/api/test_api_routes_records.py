"""Single records: runs with receipts, job polling and cancellation, drafts."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from api_support import (
    BASE_TIME,
    SIGNED_IN_VIEWER,
    Caller,
    config,
    fixture_snapshot,
    seed_case,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_cases import assert_problem

from cso.domain.enums import DraftStatus, JobStatus, Lane, Response, RunStatus
from cso.domain.models import AnalysisResult, Draft, DraftValidation
from cso.domain.receipt import build_receipt
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, DraftsRepo, RunsRepo
from cso.persistence.tables import JobRow

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"


# --------------------------------------------------------------------------- runs


async def test_run_detail_has_the_receipt_with_panel_composition_and_cross_checks(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    response = await client.get(f"{API}/runs/{seeded.run_id}")
    assert response.status_code == 200
    run = response.json()
    receipt = run["receipt"]
    assert receipt["receipt_version"] == "1" and receipt["config_version"] == run["config_version"]
    assert receipt["panel"]["ids"] and receipt["panel_composition"]["response_row"]
    assert receipt["panel_cross_checks"]
    assert receipt["decider"]["model"] == "fake-decider"
    # The summary view and the receipt agree on the same stored facts.
    assert (
        run["panel"]["composition"]["response_row"] == receipt["panel_composition"]["response_row"]
    )
    assert run["panel"]["cross_checks"] == receipt["panel_cross_checks"]
    assert run["rules_fired"] == receipt["rules_fired"]


async def test_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    assert_problem(await client.get(f"{API}/runs/{uuid4()}"), 404, "not_found")


async def test_run_without_a_receipt_is_404_with_a_clear_reason(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1, with_run=False)
    async with session_scope(factory) as session:
        run_id = await RunsRepo(session).add(
            seeded.case_id,
            seeded.snapshot_id,
            AnalysisResult(
                config_version=config()[0].version,
                status=RunStatus.SUCCEEDED,
                lane=Lane.REVIEW_SUGGESTED,
                created_at=BASE_TIME,
            ),
            receipt=None,
            now=BASE_TIME,
        )
    body = assert_problem(await client.get(f"{API}/runs/{run_id}"), 404, "not_found")
    assert "receipt" in body["detail"]
    summary = (await client.get(f"{API}/cases/{seeded.case_id}/runs")).json()["items"]
    assert [item["id"] for item in summary] == [str(run_id)]  # still listed, without a panel
    assert summary[0]["panel"] is None


async def test_failed_run_shows_its_reason_and_no_panel(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1, with_run=False)
    snapshot = await fixture_snapshot(1)
    cfg = config()[0]
    async with session_scope(factory) as session:
        run_id = await RunsRepo(session).add(
            seeded.case_id,
            seeded.snapshot_id,
            AnalysisResult(
                config_version=cfg.version,
                status=RunStatus.FAILED,
                failure_code="decider_unavailable",
                lane=Lane.RULES_ONLY,
                created_at=BASE_TIME,
                errors=["decider_unavailable"],
            ),
            receipt=build_receipt(
                snapshot.model_copy(update={"id": seeded.snapshot_id, "case_id": seeded.case_id}),
                config_version=cfg.version,
                lane=Lane.RULES_ONLY,
                errors=["decider_unavailable"],
            ),
            now=BASE_TIME,
        )
        await CasesRepo(session).record_run(
            seeded.case_id, run_id, lane=Lane.RULES_ONLY, band=None, nature=None, response=None
        )
    run = (await client.get(f"{API}/runs/{run_id}")).json()
    assert run["status"] == "failed" and run["failure_code"] == "decider_unavailable"
    assert run["panel"] is None and run["receipt"]["errors"] == ["decider_unavailable"]
    case = (await client.get(f"{API}/cases/{seeded.case_id}")).json()
    assert (
        case["lane"] == "rules_only" and case["latest_run"]["failure_code"] == "decider_unavailable"
    )


async def test_receipt_written_before_composition_fields_still_serves(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1, with_run=False)
    snapshot = await fixture_snapshot(1)
    cfg = config()[0]
    from api_support import make_panel

    async with session_scope(factory) as session:
        run_id = await RunsRepo(session).add(
            seeded.case_id,
            seeded.snapshot_id,
            AnalysisResult(
                config_version=cfg.version,
                status=RunStatus.SUCCEEDED,
                lane=Lane.REVIEW_SUGGESTED,
                created_at=BASE_TIME,
            ),
            receipt=build_receipt(  # no panel_composition or panel_cross_checks, like old rows
                snapshot.model_copy(update={"id": seeded.snapshot_id, "case_id": seeded.case_id}),
                config_version=cfg.version,
                panel=make_panel(cfg),
            ),
            now=BASE_TIME,
        )
    run = (await client.get(f"{API}/runs/{run_id}")).json()
    assert run["panel"]["composition"] is None and run["panel"]["cross_checks"] == {}
    assert run["receipt"]["panel_composition"] is None


# --------------------------------------------------------------------------- jobs


async def _queued_job(client: httpx.AsyncClient, factory: Factory) -> tuple[str, str]:
    seeded = await seed_case(factory, 1)
    response = await client.post(f"{API}/cases/{seeded.case_id}/analyses", json={"force": True})
    return str(seeded.case_id), response.json()["job_id"]


async def _set_status(factory: Factory, job_id: str, status: JobStatus) -> None:
    async with session_scope(factory) as session:
        await session.execute(
            sa.update(JobRow).where(JobRow.id == UUID(job_id)).values(status=status.value)
        )


async def test_cancelling_a_queued_job_is_immediate_and_repeatable(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    case_id, job_id = await _queued_job(client, factory)
    first = await client.post(f"{API}/jobs/{job_id}/cancel")
    assert first.status_code == 202 and first.json()["status"] == "cancelled"
    again = await client.post(f"{API}/jobs/{job_id}/cancel")
    assert again.status_code == 202 and again.json()["status"] == "cancelled"
    audit = (await client.get(f"{API}/cases/{case_id}/audit")).json()["items"]
    assert [e["action"] for e in audit].count("job.cancel_requested") == 1


async def test_cancelling_a_running_job_only_flags_it(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    _, job_id = await _queued_job(client, factory)
    await _set_status(factory, job_id, JobStatus.RUNNING)
    response = await client.post(f"{API}/jobs/{job_id}/cancel")
    assert response.status_code == 202 and response.json()["status"] == "running"
    assert (await client.post(f"{API}/jobs/{job_id}/cancel")).status_code == 202  # idempotent


async def test_cancelling_a_finished_job_is_409(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    _, job_id = await _queued_job(client, factory)
    for status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        await _set_status(factory, job_id, status)
        body = assert_problem(await client.post(f"{API}/jobs/{job_id}/cancel"), 409, "conflict")
        assert body["job_id"] == job_id


async def test_job_polling_fields_and_errors(
    client: httpx.AsyncClient, factory: Factory, caller: Caller
) -> None:
    _, job_id = await _queued_job(client, factory)
    job = (await client.get(f"{API}/jobs/{job_id}")).json()
    assert set(job) >= {"id", "kind", "status", "step", "attempts", "error", "result_ref"}
    assert job["result_ref"] is None
    assert_problem(await client.get(f"{API}/jobs/{uuid4()}"), 404, "not_found")
    assert_problem(await client.post(f"{API}/jobs/{uuid4()}/cancel"), 404, "not_found")
    caller.principal = SIGNED_IN_VIEWER
    assert (await client.get(f"{API}/jobs/{job_id}")).status_code == 200  # viewers may poll
    assert_problem(await client.post(f"{API}/jobs/{job_id}/cancel"), 403, "forbidden")


# --------------------------------------------------------------------------- drafts


async def test_draft_is_served_with_its_validation(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    assert seeded.run_id is not None
    async with session_scope(factory) as session:
        draft_id = await DraftsRepo(session).add(
            seeded.case_id,
            Draft(
                run_id=seeded.run_id,
                response_type=Response.WELCOME_AND_TIPS,
                status=DraftStatus.TEMPLATE_FALLBACK,
                model_id="template",
                greeting="Hello",
                body="Thanks for mapping.",
                closing="Happy mapping",
                cited_evidence_ids=["E1"],
                validation=DraftValidation(ok=False, violations=["too long"]),
            ),
            config_version=config()[0].version,
        )
        await CasesRepo(session).set_latest_draft(seeded.case_id, draft_id)
    draft = (await client.get(f"{API}/drafts/{draft_id}")).json()
    assert draft["status"] == "template_fallback" and draft["cited_evidence_ids"] == ["E1"]
    assert draft["validation"] == {"ok": False, "violations": ["too long"]}
    assert "config_version" not in draft
    case = (await client.get(f"{API}/cases/{seeded.case_id}")).json()
    assert case["latest_draft"]["id"] == str(draft_id)

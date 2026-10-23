"""Reviewer actions: request an analysis, request a draft, record an outcome."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from api_support import (
    ANONYMOUS,
    SIGNED_IN_VIEWER,
    Caller,
    seed_bare_cases,
    seed_case,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_cases import assert_problem

from cso.api.deps import Principal, Role
from cso.domain.enums import JobStatus
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, SessionsRepo
from cso.persistence.tables import HumanOutcomeRow, JobRow

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"
WELCOME = {"new_account_first_edits": 0.95}  # a new account: the table suggests a welcome note


async def _set_job_status(factory: Factory, job_id: str, status: JobStatus) -> None:
    async with session_scope(factory) as session:
        await session.execute(
            sa.update(JobRow).where(JobRow.id == UUID(job_id)).values(status=status.value)
        )


# --------------------------------------------------------------------------- analyses


async def test_analysis_while_one_is_queued_is_409_with_the_job_id(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post(f"{API}/cases", json={"changeset_id": 900000000001})).json()
    response = await client.post(f"{API}/cases/{created['case']['id']}/analyses", json={})
    body = assert_problem(response, 409, "conflict")
    assert body["job_id"] == created["job_id"]


async def test_current_run_gives_200_with_its_id_and_no_new_job(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    response = await client.post(f"{API}/cases/{seeded.case_id}/analyses")  # body is optional
    assert response.status_code == 200
    assert response.json() == {"run_id": str(seeded.run_id)}
    async with session_scope(factory) as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(JobRow))).scalar() == 0


async def test_force_queues_a_job_and_a_repeat_conflicts(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    url = f"{API}/cases/{seeded.case_id}/analyses"
    first = await client.post(url, json={"force": True})
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    again = await client.post(url, json={"force": True})
    assert assert_problem(again, 409, "conflict")["job_id"] == job_id
    job = (await client.get(f"{API}/jobs/{job_id}")).json()
    assert job["kind"] == "analyze" and job["status"] == "queued" and job["attempts"] == 0


async def test_a_stale_case_is_reanalysed_without_force(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    async with session_scope(factory) as session:
        await CasesRepo(session).mark_stale(seeded.case_id)
    response = await client.post(f"{API}/cases/{seeded.case_id}/analyses", json={})
    assert response.status_code == 202 and response.json()["job_id"]


async def test_analysis_errors(client: httpx.AsyncClient, caller: Caller) -> None:
    assert_problem(await client.post(f"{API}/cases/{uuid4()}/analyses", json={}), 404, "not_found")
    bad = await client.post(f"{API}/cases/{uuid4()}/analyses", json={"force": "maybe"})
    assert_problem(bad, 422, "validation_error")
    caller.principal = ANONYMOUS
    assert_problem(await client.post(f"{API}/cases/{uuid4()}/analyses"), 401, "unauthorized")
    caller.principal = SIGNED_IN_VIEWER
    assert_problem(await client.post(f"{API}/cases/{uuid4()}/analyses"), 403, "forbidden")


# --------------------------------------------------------------------------- drafts


async def _welcome_case(client: httpx.AsyncClient, factory: Factory) -> str:
    seeded = await seed_case(factory, 2, panel_probabilities=WELCOME)
    case = (await client.get(f"{API}/cases/{seeded.case_id}")).json()
    assert case["latest_run"]["response"] == "welcome_and_tips", case["latest_run"]["response"]
    return str(seeded.case_id)


async def test_draft_request_is_idempotent_per_run_and_type_until_regenerate(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    case_id = await _welcome_case(client, factory)
    url = f"{API}/cases/{case_id}/drafts"
    first = await client.post(url, json={"response_type": "welcome_and_tips"})
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    job = (await client.get(f"{API}/jobs/{job_id}")).json()
    assert job["kind"] == "draft"

    repeat = await client.post(url, json={"response_type": "welcome_and_tips"})
    assert repeat.json()["job_id"] == job_id  # same job while it is queued or running
    regenerate_while_active = await client.post(
        url, json={"response_type": "welcome_and_tips", "regenerate": True}
    )
    assert regenerate_while_active.json()["job_id"] == job_id

    await _set_job_status(factory, job_id, JobStatus.SUCCEEDED)
    done = await client.post(url, json={"response_type": "welcome_and_tips"})
    assert done.json()["job_id"] == job_id  # a finished draft is not redone
    regenerated = await client.post(
        url, json={"response_type": "welcome_and_tips", "regenerate": True}
    )
    assert regenerated.status_code == 202 and regenerated.json()["job_id"] != job_id

    await _set_job_status(factory, regenerated.json()["job_id"], JobStatus.FAILED)
    retry = await client.post(url, json={"response_type": "welcome_and_tips"})
    assert retry.json()["job_id"] not in {job_id, regenerated.json()["job_id"]}


async def test_draft_for_a_type_the_run_does_not_allow_is_409(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    case_id = await _welcome_case(client, factory)
    response = await client.post(
        f"{API}/cases/{case_id}/drafts", json={"response_type": "request_local_check"}
    )
    body = assert_problem(response, 409, "conflict")
    assert body["allowed"] == ["welcome_and_tips"]
    escalate = await client.post(
        f"{API}/cases/{case_id}/drafts", json={"response_type": "escalate_to_experienced_reviewer"}
    )
    assert_problem(escalate, 409, "conflict")


async def test_draft_without_an_analysis_or_case(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    bare = await seed_bare_cases(factory, 1)
    never = await client.post(
        f"{API}/cases/{uuid4()}/drafts", json={"response_type": "welcome_and_tips"}
    )
    assert_problem(never, 404, "not_found")
    # The bare case points at a run id that does not exist, which reads as "no analysis yet".
    none_yet = await client.post(
        f"{API}/cases/{bare[0]}/drafts", json={"response_type": "welcome_and_tips"}
    )
    assert_problem(none_yet, 409, "conflict")
    unknown_type = await client.post(f"{API}/cases/{bare[0]}/drafts", json={"response_type": "ban"})
    assert_problem(unknown_type, 422, "validation_error")


async def test_unknown_draft_is_404(client: httpx.AsyncClient) -> None:
    assert_problem(await client.get(f"{API}/drafts/{uuid4()}"), 404, "not_found")


# --------------------------------------------------------------------------- outcomes


def _outcome(run_id: object, disposition: str = "agree", **extra: object) -> dict[str, object]:
    return {"disposition": disposition, "run_id_seen": str(run_id), **extra}


async def test_outcome_needs_if_match(client: httpx.AsyncClient, factory: Factory) -> None:
    seeded = await seed_case(factory, 1)
    url = f"{API}/cases/{seeded.case_id}/outcome"
    missing = await client.put(url, json=_outcome(seeded.run_id))
    assert_problem(missing, 428, "precondition_required")
    malformed = await client.put(url, json=_outcome(seeded.run_id), headers={"If-Match": "abc"})
    assert_problem(malformed, 400, "bad_request")


async def test_recording_an_outcome_bumps_the_version_and_is_attributed(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    url = f"{API}/cases/{seeded.case_id}/outcome"
    response = await client.put(
        url,
        json=_outcome(seeded.run_id, "different_response", response_type="ask_source_question"),
        headers={"If-Match": 'W/"0"'},
    )
    assert response.status_code == 200, response.text
    case = response.json()
    assert case["outcome_version"] == 1 and case["status"] == "decided"
    assert case["latest_outcome"] == "different_response"
    assert case["latest_outcome_detail"]["reviewer_display"] == "Rae Reviewer"
    assert case["latest_outcome_detail"]["response_type"] == "ask_source_question"
    assert response.headers["etag"] == 'W/"1"'

    audit = (await client.get(f"{API}/cases/{seeded.case_id}/audit")).json()["items"]
    recorded = [e for e in audit if e["action"] == "outcome.recorded"]
    assert len(recorded) == 1 and recorded[0]["payload"]["disposition"] == "different_response"


async def test_stale_if_match_is_412_with_the_live_record_in_current(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    url = f"{API}/cases/{seeded.case_id}/outcome"
    first = await client.put(url, json=_outcome(seeded.run_id), headers={"If-Match": 'W/"0"'})
    assert first.status_code == 200
    stale = await client.put(
        url, json=_outcome(seeded.run_id, "disagree_with_model"), headers={"If-Match": 'W/"0"'}
    )
    body = assert_problem(stale, 412, "precondition_failed")
    assert isinstance(body["detail"], str)  # detail stays a string; the record is in `current`
    assert body["current"]["outcome_version"] == 1
    assert body["current"]["outcome"]["id"] == first.json()["latest_outcome_detail"]["id"]
    assert body["current"]["outcome"]["disposition"] == "agree"
    # Nothing was written by the failed attempt.
    case = (await client.get(f"{API}/cases/{seeded.case_id}")).json()
    assert case["outcome_version"] == 1 and case["latest_outcome"] == "agree"


async def test_two_writers_with_the_same_version_one_wins_one_gets_412(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    url = f"{API}/cases/{seeded.case_id}/outcome"

    async def put(disposition: str) -> int:
        response = await client.put(
            url, json=_outcome(seeded.run_id, disposition), headers={"If-Match": 'W/"0"'}
        )
        return response.status_code

    statuses = await asyncio.gather(put("agree"), put("needs_survey"))
    assert sorted(statuses) == [200, 412]


async def test_outcome_run_must_belong_to_the_case_and_roles_apply(
    client: httpx.AsyncClient, factory: Factory, caller: Caller
) -> None:
    one = await seed_case(factory, 1)
    two = await seed_case(factory, 2)
    wrong = await client.put(
        f"{API}/cases/{one.case_id}/outcome",
        json=_outcome(two.run_id),
        headers={"If-Match": 'W/"0"'},
    )
    assert_problem(wrong, 422, "validation_error")
    missing = await client.put(
        f"{API}/cases/{uuid4()}/outcome", json=_outcome(one.run_id), headers={"If-Match": 'W/"0"'}
    )
    assert_problem(missing, 404, "not_found")
    bad_body = await client.put(
        f"{API}/cases/{one.case_id}/outcome",
        json={"disposition": "ban", "run_id_seen": str(one.run_id)},
        headers={"If-Match": 'W/"0"'},
    )
    assert_problem(bad_body, 422, "validation_error")
    caller.principal = SIGNED_IN_VIEWER
    forbidden = await client.put(
        f"{API}/cases/{one.case_id}/outcome",
        json=_outcome(one.run_id),
        headers={"If-Match": 'W/"0"'},
    )
    assert_problem(forbidden, 403, "forbidden")


async def test_outcome_is_attributed_to_the_callers_session(
    client: httpx.AsyncClient, factory: Factory, caller: Caller
) -> None:
    async with session_scope(factory) as session:
        sessions = SessionsRepo(session)
        invite = await sessions.add_invite_code(code_hash="test-hash", role="reviewer")
        stored = await sessions.create_session(
            invite_code_id=invite.id,
            display_name="Real Rae",
            role="reviewer",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    caller.principal = Principal(
        id=str(stored.id),
        display_name="Real Rae",
        role=Role.REVIEWER,
        session_id=stored.id,
    )
    seeded = await seed_case(factory, 1)
    response = await client.put(
        f"{API}/cases/{seeded.case_id}/outcome",
        json=_outcome(seeded.run_id),
        headers={"If-Match": 'W/"0"'},
    )
    assert response.status_code == 200
    async with session_scope(factory) as session:
        row = (await session.execute(sa.select(HumanOutcomeRow))).scalars().one()
    assert row.session_id == stored.id and row.reviewer_display == "Real Rae"


async def test_an_edited_comment_that_breaks_the_drafting_rules_is_refused_and_not_stored(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    """F-M4: the backend checks `final_text`; the outcome stays as it was."""
    seeded = await seed_case(factory, 1)
    url = f"{API}/cases/{seeded.case_id}/outcome"
    bad_texts = (
        "Hello, you must fix this.",
        "Hello, this looks like spаm to me.",  # Cyrillic a
        "Hello, please s​top.",
        "Hello <b>there</b>",
        "Hello, see https://evil.example.com/page",
        "x" * 1001,
    )
    for text in bad_texts:
        response = await client.put(
            url,
            json=_outcome(seeded.run_id, "different_response", final_text=text),
            headers={"If-Match": 'W/"0"'},
        )
        body = assert_problem(response, 422, "final_text_invalid")
        assert body["violations"], text
        assert "must" not in str(body) and "spam" not in str(body).lower()
    case = (await client.get(f"{API}/cases/{seeded.case_id}")).json()
    assert case["outcome_version"] == 0 and case["latest_outcome"] is None
    async with factory() as session:
        rows = (
            await session.execute(sa.select(sa.func.count()).select_from(HumanOutcomeRow))
        ).scalar_one()
    assert rows == 0

    ok = await client.put(
        url,
        json=_outcome(
            seeded.run_id, "different_response", final_text="Hello, could you add a source?"
        ),
        headers={"If-Match": 'W/"0"'},
    )
    assert ok.status_code == 200

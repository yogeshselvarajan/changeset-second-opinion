"""Contract gaps closed after the web work: `allowed_responses`, `evidence_id`, 409 `job_id`."""

from __future__ import annotations

import re
from uuid import uuid4

import httpx
from api_support import config, fixture_snapshot, seed_case
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_actions import WELCOME
from test_api_routes_cases import assert_problem

from cso.domain.draft_validation import evidence_ids
from cso.domain.enums import Response, RunStatus
from cso.domain.evidence import render
from cso.domain.lanes import COMMENT_TYPES, evaluate_panel_run
from cso.domain.models import AnalysisResult
from cso.domain.receipt import build_receipt
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, RunsRepo

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"
EVIDENCE_LINE = re.compile(r"^(E\d+) (node|way|relation)/(\d+) ", re.MULTILINE)


async def _detail(client: httpx.AsyncClient, case_id: object) -> dict[str, object]:
    response = await client.get(f"{API}/cases/{case_id}")
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def _store_failed_run(factory: Factory, number: int) -> object:
    """A case whose only run failed, stored the way the worker stores it."""
    seeded = await seed_case(factory, number, with_run=False)
    cfg, _ = config()
    snapshot = (await fixture_snapshot(number)).model_copy(
        update={"id": seeded.snapshot_id, "case_id": seeded.case_id}
    )
    outcome = evaluate_panel_run(snapshot, None, cfg, failure_code="decider_unavailable")
    analysis = AnalysisResult(
        id=uuid4(),
        snapshot_id=seeded.snapshot_id,
        config_version=cfg.version,
        status=RunStatus.FAILED,
        failure_code="decider_unavailable",
        errors=["decider_unavailable"],
        **outcome.result_fields(),
    )
    receipt = build_receipt(
        snapshot,
        config_version=cfg.version,
        timing_ms={"total": 10},
        band=outcome.band,
        rules_fired=outcome.rule_hits,
        lane=outcome.lane,
        errors=["decider_unavailable"],
    )
    async with session_scope(factory) as session:
        run_id = await RunsRepo(session).add(
            seeded.case_id, seeded.snapshot_id, analysis, receipt=receipt
        )
        await CasesRepo(session).record_run(
            seeded.case_id,
            run_id,
            lane=analysis.lane,
            band=analysis.band,
            nature=analysis.nature,
            response=analysis.response,
        )
    return seeded.case_id


# --------------------------------------------------------------------------- allowed_responses


async def test_allowed_responses_follow_the_latest_run(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 2, panel_probabilities=WELCOME)
    detail = await _detail(client, seeded.case_id)
    assert detail["allowed_responses"] == ["welcome_and_tips"]


async def test_the_draft_endpoint_and_allowed_responses_agree_for_every_response_type(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 2, panel_probabilities=WELCOME)
    allowed = (await _detail(client, seeded.case_id))["allowed_responses"]
    assert isinstance(allowed, list) and allowed
    for response_type in Response:
        posted = await client.post(
            f"{API}/cases/{seeded.case_id}/drafts", json={"response_type": response_type.value}
        )
        if response_type.value in allowed:
            assert posted.status_code == 202, (response_type, posted.text)
        else:
            assert_problem(posted, 409, "conflict")


async def test_allowed_responses_only_hold_comment_types(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    for number in (1, 2, 5):
        seeded = await seed_case(factory, number)
        allowed = (await _detail(client, seeded.case_id))["allowed_responses"]
        assert isinstance(allowed, list)
        assert {Response(r) for r in allowed} <= COMMENT_TYPES


async def test_allowed_responses_are_empty_without_an_analysis(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 2, with_run=False)
    assert (await _detail(client, seeded.case_id))["allowed_responses"] == []
    posted = await client.post(
        f"{API}/cases/{seeded.case_id}/drafts", json={"response_type": "welcome_and_tips"}
    )
    assert_problem(posted, 409, "conflict")


async def test_allowed_responses_are_empty_when_the_latest_run_failed(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    case_id = await _store_failed_run(factory, 2)
    detail = await _detail(client, case_id)
    assert detail["latest_run"]["status"] == "failed"  # type: ignore[index]
    assert detail["allowed_responses"] == []
    posted = await client.post(
        f"{API}/cases/{case_id}/drafts", json={"response_type": "welcome_and_tips"}
    )
    assert_problem(posted, 409, "conflict")


async def test_allowed_responses_are_empty_when_the_case_is_stale(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 2, panel_probabilities=WELCOME)
    assert (await _detail(client, seeded.case_id))["allowed_responses"] == ["welcome_and_tips"]
    async with session_scope(factory) as session:
        await CasesRepo(session).mark_stale(seeded.case_id)
    detail = await _detail(client, seeded.case_id)
    assert detail["stale"] is True
    assert detail["allowed_responses"] == []
    posted = await client.post(
        f"{API}/cases/{seeded.case_id}/drafts", json={"response_type": "welcome_and_tips"}
    )
    body = assert_problem(posted, 409, "conflict")
    assert body["allowed"] == []
    assert "request a new analysis" in str(body["detail"])


# --------------------------------------------------------------------------- evidence_id


def _ids_in_text(text: str) -> dict[tuple[str, int], str]:
    return {(kind, int(osm_id)): eid for eid, kind, osm_id in EVIDENCE_LINE.findall(text)}


async def _evidence(client: httpx.AsyncClient, case_id: object) -> dict[str, object]:
    response = await client.get(f"{API}/cases/{case_id}/evidence")
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_evidence_ids_equal_the_ids_in_the_compact_evidence_text(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    cfg, _ = config()
    for number in (1, 2, 4, 8):
        seeded = await seed_case(factory, number)
        body = await _evidence(client, seeded.case_id)
        snapshot = await fixture_snapshot(number)
        shown = _ids_in_text(render(snapshot, cfg, profile="compact").text)
        assert shown, number
        api_ids = {
            (e["osm_type"], e["osm_id"]): e["evidence_id"]
            for e in body["elements"]  # type: ignore[attr-defined]
            if e["evidence_id"] is not None
        }
        assert api_ids == shown, number


async def test_evidence_ids_follow_the_text_order_not_the_collection_order(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 4)  # deletions are ranked first in the text
    body = await _evidence(client, seeded.case_id)
    elements = body["elements"]
    assert isinstance(elements, list)
    ids = [e["evidence_id"] for e in elements if e["evidence_id"] is not None]
    assert "E1" in ids
    first = next(e for e in elements if e["evidence_id"] == "E1")
    assert first["action"] == "delete"
    assert len(ids) == len(set(ids))


async def test_elements_the_text_leaves_out_have_a_null_evidence_id(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 3)  # more elements than the compact text shows
    body = await _evidence(client, seeded.case_id)
    elements = body["elements"]
    assert isinstance(elements, list)
    with_id = [e for e in elements if e["evidence_id"] is not None]
    without = [e for e in elements if e["evidence_id"] is None]
    assert with_id and without
    assert len(with_id) <= 12  # the compact text shows at most 12 changed objects
    for element in elements:
        assert element["evidence_id"] is None or re.fullmatch(
            r"E[1-9][0-9]*", element["evidence_id"]
        )


async def test_evidence_without_a_stored_run_still_gets_ids(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 2, with_run=False)  # falls back to the active config
    body = await _evidence(client, seeded.case_id)
    elements = body["elements"]
    assert isinstance(elements, list)
    assert any(e["evidence_id"] for e in elements)


async def test_the_ids_a_draft_may_cite_are_the_api_evidence_ids(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    """The draft validator accepts `E<n>` ids from the compact text; the API names the same ids."""
    cfg, _ = config()
    for number in (2, 4):
        seeded = await seed_case(factory, number)
        body = await _evidence(client, seeded.case_id)
        elements = body["elements"]
        assert isinstance(elements, list)
        api_ids = {e["evidence_id"] for e in elements if e["evidence_id"]}
        rendered = render(await fixture_snapshot(number), cfg, profile="compact")
        citable = {i for i in evidence_ids(rendered) if i.startswith("E")}
        assert api_ids == citable, number


# --------------------------------------------------------------------------- 409 job_id


async def test_analysis_conflict_carries_the_existing_job_id_and_the_contract_says_so(
    client: httpx.AsyncClient, factory: Factory, app: FastAPI
) -> None:
    seeded = await seed_case(factory, 2, panel_probabilities=WELCOME)
    first = await client.post(f"{API}/cases/{seeded.case_id}/analyses", json={"force": True})
    assert first.status_code == 202
    again = await client.post(f"{API}/cases/{seeded.case_id}/analyses", json={"force": True})
    body = assert_problem(again, 409, "conflict")
    assert body["job_id"] == first.json()["job_id"]
    spec = app.openapi()
    description = spec["paths"][f"{API}/cases/{{id}}/analyses"]["post"]["responses"]["409"][
        "description"
    ]
    assert "job_id" in description


async def test_openapi_declares_the_new_fields(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]
    assert "allowed_responses" in schemas["CaseDetail"]["properties"]
    assert "evidence_id" in schemas["ChangedElement"]["properties"]
    assert schemas["EvidenceSnapshot"]["properties"]["elements"]["items"]["$ref"].endswith(
        "/ChangedElement"
    )

"""The shareable receipt: public, allow-listed, rate limited."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
from api_support import seed_case
from auth_support import make_config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_cases import assert_problem

from cso.api.deps import get_principal
from cso.api.v1.receipts import RECEIPT_PER_IP_MINUTE
from cso.domain.enums import Disposition
from cso.domain.models import OutcomeInput
from cso.persistence.db import session_scope
from cso.persistence.repos import OutcomesRepo

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"

TOP_LEVEL = {
    "run_id",
    "changeset_id",
    "created_at",
    "config_version",
    "pack_id",
    "calibration_version",
    "decider",
    "lane",
    "band",
    "nature",
    "response",
    "probes",
    "rules_fired",
    "coverage",
    "attribution",
}
PROBE = {"code", "label", "probability", "reading"}
RULE = {"code", "label", "severity"}
COVERAGE = {"score", "elements_in_changeset", "elements_detailed", "history_gaps_count"}
DECIDER = {"model", "checkpoint"}
ATTRIBUTION = {"copyright", "attribution", "license"}


async def test_a_receipt_is_readable_without_an_account(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    response = await client.get(f"{API}/receipts/{seeded.run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(seeded.run_id)
    assert body["probes"] and body["coverage"]["elements_in_changeset"] >= 0
    assert body["attribution"]["copyright"] == "OpenStreetMap contributors"
    assert body["lane"]


async def test_only_allow_listed_fields_appear(client: httpx.AsyncClient, factory: Factory) -> None:
    seeded = await seed_case(factory, 1)
    body = (await client.get(f"{API}/receipts/{seeded.run_id}")).json()
    assert set(body) == TOP_LEVEL
    assert body["probes"] and all(set(p) == PROBE for p in body["probes"])
    assert all(set(r) == RULE for r in body["rules_fired"])
    assert set(body["coverage"]) == COVERAGE
    assert body["decider"] is None or set(body["decider"]) == DECIDER
    assert set(body["attribution"]) == ATTRIBUTION


async def test_no_reviewer_or_decision_detail_leaks(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    assert seeded.run_id is not None
    async with session_scope(factory) as session:
        await OutcomesRepo(session).append(
            seeded.case_id,
            OutcomeInput(
                run_id_seen=seeded.run_id,
                disposition=Disposition.AGREE,
                note="Private note from the reviewer",
            ),
            reviewer_display="Rae Reviewer",
            session_id=None,
            expected_version=0,
        )
    text = json.dumps((await client.get(f"{API}/receipts/{seeded.run_id}")).json())
    for forbidden in (
        "Rae Reviewer",
        "Private note",
        "reviewer",
        "session",
        "outcome",
        "rendered_text",
        "final_text",
        "triggered_by",
    ):
        assert forbidden not in text, forbidden


async def test_unknown_receipt_is_404(client: httpx.AsyncClient) -> None:
    assert_problem(await client.get(f"{API}/receipts/{uuid4()}"), 404, "not_found")


async def test_live_mode_still_serves_the_receipt_but_not_the_queue(
    app: FastAPI, client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    app.dependency_overrides.pop(get_principal, None)
    app.state.auth_config = make_config(mode="live")
    assert (await client.get(f"{API}/receipts/{seeded.run_id}")).status_code == 200
    assert (await client.get(f"{API}/cases")).status_code == 401


async def test_the_sixty_first_request_in_a_minute_is_rate_limited(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    url = f"{API}/receipts/{seeded.run_id}"
    for _ in range(RECEIPT_PER_IP_MINUTE):
        assert (await client.get(url)).status_code == 200
    limited = await client.get(url)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1

"""Bulk import: explicit ids, MapRoulette challenges through a seam, and its errors."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from api_support import ANONYMOUS, SIGNED_IN_VIEWER, Caller
from fastapi import FastAPI
from test_api_routes_cases import assert_problem

from cso.api.v1.cases import get_challenge_lister
from cso.jobs.imports import ChallengeLister, ChallengeSourceError

API = "/api/v1"


class FakeLister:
    """A challenge source that returns scripted ids (and records what it was asked)."""

    def __init__(self, ids: list[int] | None = None, fail: bool = False) -> None:
        self.ids = ids or []
        self.fail = fail
        self.asked: list[tuple[int, int]] = []
        self.closed = False

    async def list_changeset_ids(self, challenge_id: int, limit: int) -> list[int]:
        self.asked.append((challenge_id, limit))
        if self.fail:
            raise ChallengeSourceError("network down")
        return self.ids[:limit]

    async def aclose(self) -> None:
        self.closed = True


def _use(app: FastAPI, lister: FakeLister) -> None:
    async def dependency() -> AsyncIterator[ChallengeLister]:
        try:
            yield lister
        finally:
            await lister.aclose()

    app.dependency_overrides[get_challenge_lister] = dependency


async def test_import_by_ids_is_idempotent_per_id(client: httpx.AsyncClient) -> None:
    body = {"source": "osmcha", "ids": [900000000001, 900000000002, 900000000002]}
    first = await client.post(f"{API}/cases/import", json=body)
    assert first.status_code == 202
    assert first.json()["created"] == 2 and first.json()["existing"] == 0
    assert len(first.json()["job_ids"]) == 2  # a duplicate id in the request counts once
    again = await client.post(f"{API}/cases/import", json=body)
    assert again.json()["created"] == 0 and again.json()["existing"] == 2
    assert sorted(again.json()["job_ids"]) == sorted(first.json()["job_ids"])  # same queued jobs


async def test_challenge_import_in_replay_mode_explains_itself(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{API}/cases/import", json={"source": "maproulette", "challenge_id": 55814}
    )
    body = assert_problem(response, 400, "bad_request")
    assert "live mode" in body["detail"]


async def test_challenge_import_uses_the_source_and_filters_ids(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    lister = FakeLister([900000000010, 900000000011, 0, 10**14, 900000000010, 900000000012])
    _use(app, lister)
    response = await client.post(
        f"{API}/cases/import",
        json={"source": "maproulette", "challenge_id": 55814, "limit": 3, "ids": [900000000099]},
    )
    assert response.status_code == 202
    body = response.json()
    # Explicit ids first, then the challenge's ids (invalid and repeated ones dropped), capped at 3.
    assert body["created"] == 3 and body["existing"] == 0
    assert lister.asked == [(55814, 3)] and lister.closed
    listing = (await client.get(f"{API}/cases", params={"limit": 100})).json()
    assert {c["changeset_id"] for c in listing["items"]} == {
        900000000099, 900000000010, 900000000011,
    }  # fmt: skip


async def test_an_unreachable_source_is_502(app: FastAPI, client: httpx.AsyncClient) -> None:
    _use(app, FakeLister(fail=True))
    response = await client.post(
        f"{API}/cases/import", json={"source": "maproulette", "challenge_id": 1}
    )
    assert_problem(response, 502, "upstream_unavailable")


async def test_import_request_errors_and_roles(
    app: FastAPI, client: httpx.AsyncClient, caller: Caller
) -> None:
    _use(app, FakeLister([1]))
    osmcha_challenge = await client.post(
        f"{API}/cases/import", json={"source": "osmcha", "challenge_id": 3}
    )
    assert_problem(osmcha_challenge, 400, "bad_request")
    no_selector = await client.post(f"{API}/cases/import", json={"source": "maproulette"})
    assert_problem(no_selector, 422, "validation_error")
    too_many = await client.post(
        f"{API}/cases/import", json={"source": "osmcha", "ids": list(range(1, 102))}
    )
    assert_problem(too_many, 422, "validation_error")
    caller.principal = ANONYMOUS
    body = {"source": "osmcha", "ids": [1]}
    assert_problem(await client.post(f"{API}/cases/import", json=body), 401, "unauthorized")
    caller.principal = SIGNED_IN_VIEWER
    assert_problem(await client.post(f"{API}/cases/import", json=body), 403, "forbidden")


async def test_import_is_refused_when_its_ids_do_not_fit_the_remaining_daily_cap(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """F-M9: one call cannot queue past the daily analysis cap."""
    from cso.api.db import app_settings
    from cso.settings import Settings

    app.dependency_overrides[app_settings] = lambda: Settings(daily_analysis_cap=3)
    one = await client.post(f"{API}/cases", json={"changeset_id": 900000000500})
    assert one.status_code == 201  # 1 of 3 used
    too_many = {"source": "osmcha", "ids": [900000000501, 900000000502, 900000000503]}
    refused = await client.post(f"{API}/cases/import", json=too_many)
    assert refused.status_code == 429
    assert refused.json()["cap"] == "analyze"
    fits = await client.post(f"{API}/cases/import", json={**too_many, "ids": too_many["ids"][:2]})
    assert fits.status_code == 202 and fits.json()["created"] == 2
    # nothing from the refused call was queued
    listing = await client.get(f"{API}/cases", params={"q": "900000000503"})
    assert listing.status_code == 200 and listing.json()["items"] == []


async def test_import_charges_the_quota_per_id(app: FastAPI, client: httpx.AsyncClient) -> None:
    from cso.api.auth_core import AuthConfig
    from cso.api.security import get_limiter

    capacity = (
        AuthConfig().analysis_per_ip_hour
    )  # the test app resolves the quota caller as anonymous
    ids = list(range(900000000600, 900000000605))
    first = await client.post(f"{API}/cases/import", json={"source": "osmcha", "ids": ids})
    assert first.status_code == 202
    (bucket,) = [v for k, v in get_limiter(app)._state.items() if k.startswith("analysis:")]
    tokens, _ = bucket
    assert tokens == pytest.approx(capacity - len(ids), abs=0.01)
    many = {"source": "osmcha", "ids": list(range(900000000700, 900000000700 + capacity))}
    refused = await client.post(f"{API}/cases/import", json=many)
    assert refused.status_code == 429
    assert "retry-after" in refused.headers


async def test_anonymous_callers_are_refused_before_a_quota_token_is_taken(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """F-L9: the role check runs before the quota dependency on every POST route."""
    from cso.api.security import get_limiter

    app_caller = Caller(ANONYMOUS)
    from cso.api.deps import get_principal

    app.dependency_overrides[get_principal] = lambda: app_caller.principal
    case_id = "00000000-0000-0000-0000-000000000001"
    for method, url, body in (
        ("POST", f"{API}/cases", {"changeset_id": 900000000700}),
        ("POST", f"{API}/cases/import", {"source": "osmcha", "ids": [900000000701]}),
        ("POST", f"{API}/cases/{case_id}/analyses", None),
        ("POST", f"{API}/cases/{case_id}/drafts", {"response_type": "welcome_and_tips"}),
    ):
        response = await client.request(method, url, json=body)
        assert response.status_code == 401, url
    state = get_limiter(app)._state
    assert not [k for k in state if k.startswith(("analysis:", "draft:"))]

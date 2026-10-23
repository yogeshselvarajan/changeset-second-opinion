"""Decision history, CSV export, configuration and readiness."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from pathlib import Path

import httpx
from api_support import (
    ADMIN,
    ANONYMOUS,
    BASE_TIME,
    REVIEWER,
    SIGNED_IN_VIEWER,
    Caller,
    config,
    seed_case,
)
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_cases import assert_problem

from cso.api.db import app_settings
from cso.api.schemas import DeciderHealth
from cso.domain.enums import Disposition
from cso.domain.models import OutcomeInput
from cso.persistence.db import make_engine, make_sessionmaker, session_scope
from cso.persistence.repos import OutcomesRepo
from cso.settings import Settings

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"
REAL_UA = "ChangesetSecondOpinion/0.1 (+https://example.org/cso; maintainer@example.org)"


async def _record(
    factory: Factory,
    number: int,
    disposition: Disposition,
    reviewer: str,
    minutes: int,
) -> None:
    seeded = await seed_case(factory, number)
    assert seeded.run_id is not None
    async with session_scope(factory) as session:
        await OutcomesRepo(session).append(
            seeded.case_id,
            OutcomeInput(disposition=disposition, run_id_seen=seeded.run_id),
            reviewer_display=reviewer,
            session_id=None,
            expected_version=0,
            now=BASE_TIME + timedelta(minutes=minutes),
        )


async def _three_decisions(factory: Factory) -> None:
    await _record(factory, 1, Disposition.AGREE, "Rae Reviewer", 1)
    await _record(factory, 2, Disposition.NEEDS_SURVEY, "=cmd|' /C calc'!A0", 2)
    await _record(factory, 4, Disposition.AGREE, "Rae Reviewer", 3)


# --------------------------------------------------------------------------- decisions


async def test_decisions_are_newest_first_with_the_lane_the_reviewer_saw(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    await _three_decisions(factory)
    body = (await client.get(f"{API}/decisions")).json()
    assert [row["changeset_id"] for row in body["items"]] == [
        900000000004,
        900000000002,
        900000000001,
    ]
    row = body["items"][0]
    assert set(row) == {
        "outcome_id", "case_id", "changeset_id", "disposition", "response_type",
        "lane_at_decision", "band_at_decision", "reviewer_display", "created_at",
        "config_version", "decider_model",
    }  # fmt: skip
    assert row["lane_at_decision"] in {
        "review_suggested", "insufficient_evidence", "needs_local_knowledge", "rules_only",
        "looks_consistent",
    }  # fmt: skip
    assert row["config_version"] == config()[0].version and row["decider_model"] == "fake-decider"


async def test_decision_filters_and_paging(client: httpx.AsyncClient, factory: Factory) -> None:
    await _three_decisions(factory)
    by_reviewer = (await client.get(f"{API}/decisions", params={"reviewer": "Rae Reviewer"})).json()
    assert len(by_reviewer["items"]) == 2
    by_disposition = (
        await client.get(f"{API}/decisions", params={"disposition": "needs_survey"})
    ).json()
    assert [r["changeset_id"] for r in by_disposition["items"]] == [900000000002]
    since = (BASE_TIME + timedelta(minutes=2)).isoformat()
    ranged = (await client.get(f"{API}/decisions", params={"from": since})).json()
    assert [r["changeset_id"] for r in ranged["items"]] == [900000000004, 900000000002]
    until = (BASE_TIME + timedelta(minutes=2)).isoformat()
    upto = (await client.get(f"{API}/decisions", params={"to": until})).json()
    assert [r["changeset_id"] for r in upto["items"]] == [900000000002, 900000000001]

    first = (await client.get(f"{API}/decisions", params={"limit": 2})).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    last = (
        await client.get(f"{API}/decisions", params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()
    assert [r["changeset_id"] for r in last["items"]] == [900000000001]
    assert last["next_cursor"] is None
    bad = await client.get(f"{API}/decisions", params={"disposition": "ban"})
    assert_problem(bad, 400, "validation_error")


# --------------------------------------------------------------------------- export


async def test_csv_export_is_admin_only(
    client: httpx.AsyncClient, factory: Factory, caller: Caller
) -> None:
    await _three_decisions(factory)
    caller.principal = ANONYMOUS
    assert_problem(await client.get(f"{API}/decisions/export.csv"), 401, "unauthorized")
    for principal in (SIGNED_IN_VIEWER, REVIEWER):
        caller.principal = principal
        assert_problem(await client.get(f"{API}/decisions/export.csv"), 403, "forbidden")


async def test_csv_export_has_a_header_filters_and_defuses_formulas(
    client: httpx.AsyncClient, factory: Factory, caller: Caller
) -> None:
    await _three_decisions(factory)
    caller.principal = ADMIN
    response = await client.get(f"{API}/decisions/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="decisions.csv"' in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:4] == ["outcome_id", "case_id", "changeset_id", "disposition"]
    assert len(rows) == 4
    reviewer_cells = {row[rows[0].index("reviewer_display")] for row in rows[1:]}
    assert "'=cmd|' /C calc'!A0" in reviewer_cells  # a leading '=' cannot run as a formula
    assert not any(cell.startswith(("=", "+", "-", "@")) for row in rows[1:] for cell in row)

    filtered = await client.get(f"{API}/decisions/export.csv", params={"disposition": "agree"})
    assert len(list(csv.reader(io.StringIO(filtered.text)))) == 3


# --------------------------------------------------------------------------- config


async def test_config_is_served_to_viewers_and_matches_the_active_version(
    client: httpx.AsyncClient, factory: Factory, caller: Caller
) -> None:
    caller.principal = ANONYMOUS
    before = (await client.get(f"{API}/config")).json()  # nothing stored: the default config
    assert before["version"] == config()[0].version
    await seed_case(factory, 1)  # stores and activates the config
    caller.principal = SIGNED_IN_VIEWER
    stored = (await client.get(f"{API}/config")).json()
    assert stored == before
    assert {"option_sets", "bands", "rules", "tone", "panel"} <= set(stored)


async def test_config_versions_are_admin_only(
    client: httpx.AsyncClient, factory: Factory, caller: Caller
) -> None:
    await seed_case(factory, 1)
    assert_problem(await client.get(f"{API}/config/versions"), 403, "forbidden")  # reviewer
    caller.principal = ADMIN
    items = (await client.get(f"{API}/config/versions")).json()["items"]
    assert len(items) == 1
    assert items[0]["version"] == config()[0].version
    assert f"sha256:{items[0]['sha']}" == items[0]["version"]


# --------------------------------------------------------------------------- readiness


def _live_settings() -> Settings:
    return Settings(mode="live", user_agent=REAL_UA)


async def test_readyz_is_ok_in_replay_mode_without_a_model_server(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {
        "db": True,
        "decider": {"ok": False, "model": None, "checkpoint": None, "device": None},
    }
    assert (await client.get("/healthz")).json() == {"status": "ok"}


async def test_readyz_503_when_the_database_is_not_migrated(app: FastAPI, tmp_path: Path) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")  # no tables
    app.state.session_factory = make_sessionmaker(engine)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            body = assert_problem(await http.get("/readyz"), 503, "service_unavailable")
    finally:
        await engine.dispose()
    assert body["db"] is False


async def test_readyz_in_live_mode_needs_the_model_server_and_caches_the_probe(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[app_settings] = _live_settings
    down = assert_problem(await client.get("/readyz"), 503, "service_unavailable")
    assert down["db"] is True and down["decider"]["ok"] is False

    calls = 0

    async def probe() -> DeciderHealth:
        nonlocal calls
        calls += 1
        return DeciderHealth(ok=True, model="m", checkpoint="c/m", device="cuda")

    app.state.decider_probe = probe
    app.state.decider_health_cache = None  # forget the cached "down" answer
    first = await client.get("/readyz")
    second = await client.get("/readyz")
    assert first.status_code == second.status_code == 200
    assert first.json()["decider"] == {
        "ok": True,
        "model": "m",
        "checkpoint": "c/m",
        "device": "cuda",
    }
    assert calls == 1  # cached for ten seconds

"""Community packs over HTTP: list, activate (admin, audited), diff, and what stays unchanged."""

from __future__ import annotations

import httpx
import sqlalchemy as sa
from api_support import ADMIN, REVIEWER, Caller, seed_case
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_cases import assert_problem

from cso.domain.config import BANNED_WORDS_FLOOR
from cso.persistence.db import session_scope
from cso.persistence.repos import ConfigsRepo, RunsRepo
from cso.persistence.tables import AuditEventRow

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"


async def test_the_pack_list_marks_the_default_as_active_until_one_is_chosen(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"{API}/config/packs")
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert set(items) == {"default", "newcomer-friendly", "strict-review", "hi-in"}
    assert [pack_id for pack_id, item in items.items() if item["is_active"]] == ["default"]
    assert all(item["title"] and item["author"] for item in items.values())


async def test_only_an_admin_can_activate_a_pack(client: httpx.AsyncClient, caller: Caller) -> None:
    caller.principal = REVIEWER
    assert_problem(
        await client.post(f"{API}/config/packs/strict-review/activate"), 403, "forbidden"
    )
    caller.principal = ADMIN
    assert (await client.post(f"{API}/config/packs/strict-review/activate")).status_code == 200


async def test_activation_changes_the_active_pack_and_writes_an_audit_event(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    caller.principal = ADMIN
    response = await client.post(f"{API}/config/packs/strict-review/activate")
    body = response.json()
    assert body["pack"]["id"] == "strict-review" and body["pack"]["is_active"] is True

    listed = (await client.get(f"{API}/config/packs")).json()["items"]
    assert [i["id"] for i in listed if i["is_active"]] == ["strict-review"]
    active = (await client.get(f"{API}/config")).json()
    assert active["id"] == "strict-review" and active["version"] == body["config_version"]

    async with session_scope(factory) as session:
        stored = await ConfigsRepo(session).get_active()
        events = (
            (
                await session.execute(
                    sa.select(AuditEventRow).where(AuditEventRow.action == "config.pack_activated")
                )
            )
            .scalars()
            .all()
        )
    assert stored is not None and stored.version == body["config_version"]
    assert stored.pack_id == "strict-review"
    assert len(events) == 1
    assert events[0].payload["pack_id"] == "strict-review"
    assert events[0].actor.startswith("admin:")


async def test_runs_already_made_keep_the_version_they_used(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    assert seeded.run_id is not None
    async with session_scope(factory) as session:
        before = (await RunsRepo(session).get_row(seeded.run_id)).config_version  # type: ignore[union-attr]
    caller.principal = ADMIN
    assert (await client.post(f"{API}/config/packs/newcomer-friendly/activate")).status_code == 200
    async with session_scope(factory) as session:
        after = (await RunsRepo(session).get_row(seeded.run_id)).config_version  # type: ignore[union-attr]
    assert before == after
    run = (await client.get(f"{API}/runs/{seeded.run_id}")).json()
    assert run["config_version"] == before


async def test_activating_twice_is_harmless(client: httpx.AsyncClient, caller: Caller) -> None:
    caller.principal = ADMIN
    first = (await client.post(f"{API}/config/packs/hi-in/activate")).json()
    second = (await client.post(f"{API}/config/packs/hi-in/activate")).json()
    assert first["config_version"] == second["config_version"]


async def test_an_unknown_pack_is_404(client: httpx.AsyncClient, caller: Caller) -> None:
    caller.principal = ADMIN
    assert_problem(await client.post(f"{API}/config/packs/nope/activate"), 404, "not_found")


async def test_the_diff_names_what_differs_and_is_symmetric(client: httpx.AsyncClient) -> None:
    forward = (
        await client.get(f"{API}/config/diff", params={"a": "default", "b": "strict-review"})
    ).json()
    backward = (
        await client.get(f"{API}/config/diff", params={"a": "strict-review", "b": "default"})
    ).json()
    assert forward["a"] == "default" and forward["b"] == "strict-review"
    assert [(c["area"], c["key"]) for c in forward["changes"]] == [
        (c["area"], c["key"]) for c in backward["changes"]
    ]
    r1 = next(c for c in forward["changes"] if c["key"] == "R1.min_age_days")
    assert (r1["a"], r1["b"]) == ("365", "180")


async def test_the_diff_never_carries_the_banned_words(client: httpx.AsyncClient) -> None:
    text = (
        await client.get(f"{API}/config/diff", params={"a": "default", "b": "newcomer-friendly"})
    ).text
    for word in BANNED_WORDS_FLOOR:
        assert word not in text


async def test_diff_with_an_unknown_pack_is_404(client: httpx.AsyncClient) -> None:
    assert_problem(
        await client.get(f"{API}/config/diff", params={"a": "default", "b": "nope"}),
        404,
        "not_found",
    )


async def test_the_receipt_names_the_pack_of_its_run(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    body = (await client.get(f"{API}/receipts/{seeded.run_id}")).json()
    assert body["pack_id"] == "default"

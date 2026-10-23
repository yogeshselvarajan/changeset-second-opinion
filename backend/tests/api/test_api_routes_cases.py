"""Case endpoints: queue, create (idempotent), detail, evidence, runs, audit, paging."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
from api_support import (
    ANONYMOUS,
    SIGNED_IN_VIEWER,
    Caller,
    seed_bare_cases,
    seed_case,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import Lane

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["type"] == f"urn:cso:problem:{code}"
    assert body["status"] == status and body["request_id"] and body["instance"]
    return body


# --------------------------------------------------------------------------- create


async def test_create_case_twice_gives_201_then_200_with_the_same_case(
    client: httpx.AsyncClient,
) -> None:
    first = await client.post(f"{API}/cases", json={"changeset_id": 900000000001})
    assert first.status_code == 201
    body = first.json()
    assert body["job_id"] and body["case"]["status"] == "analyzing"
    assert body["case"]["changeset"] is None  # no snapshot until the worker has run
    assert first.headers["etag"] == 'W/"0"'

    second = await client.post(f"{API}/cases", json={"changeset_id": 900000000001})
    assert second.status_code == 200
    again = second.json()
    assert again["case"]["id"] == body["case"]["id"]
    assert again["job_id"] == body["job_id"]  # the queued job is still the one to wait for


async def test_create_case_rejects_bad_ids_with_problem_json(client: httpx.AsyncClient) -> None:
    for bad in (0, -5, 10**13, "abc"):
        response = await client.post(f"{API}/cases", json={"changeset_id": bad})
        body = assert_problem(response, 400, "validation_error")
        assert body["errors"] and "input" not in str(body["errors"])
    unknown = await client.post(f"{API}/cases", json={"changeset_id": 1, "extra": True})
    assert_problem(unknown, 422, "validation_error")


async def test_twelve_digit_fixture_ids_are_accepted(client: httpx.AsyncClient) -> None:
    response = await client.post(f"{API}/cases", json={"changeset_id": 900000000999})
    assert response.status_code == 201


async def test_creating_needs_a_reviewer(client: httpx.AsyncClient, caller: Caller) -> None:
    caller.principal = ANONYMOUS
    assert_problem(await client.post(f"{API}/cases", json={"changeset_id": 1}), 401, "unauthorized")
    caller.principal = SIGNED_IN_VIEWER
    assert_problem(await client.post(f"{API}/cases", json={"changeset_id": 1}), 403, "forbidden")
    listing = await client.get(f"{API}/cases")  # reading stays open to viewers
    assert listing.status_code == 200


# --------------------------------------------------------------------------- detail, evidence, runs


async def test_detail_carries_run_panel_and_etag(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 1)
    response = await client.get(f"{API}/cases/{seeded.case_id}")
    assert response.status_code == 200
    case = response.json()
    assert case["changeset_id"] == seeded.changeset_id
    assert case["changeset"]["id"] == seeded.changeset_id
    assert case["latest_snapshot_id"] == str(seeded.snapshot_id)
    assert response.headers["etag"] == f'W/"{case["outcome_version"]}"'

    run = case["latest_run"]
    assert run["id"] == str(seeded.run_id) and run["status"] == "succeeded"
    assert (
        set(run["nature_probabilities"])
        <= {
            "consistent_edit",
            "likely_good_faith_mistake",
            "possible_deliberate_damage",
            "needs_local_knowledge",
        }
        or run["nature_probabilities"] == {}
    )
    panel = run["panel"]
    assert len(panel["probes"]) == 10
    assert {p["reading"] for p in panel["probes"]} <= {"no", "unknown", "yes"}
    assert panel["composition"]["response_row"] and panel["composition"]["nature_row"]
    assert panel["cross_checks"]  # compared with facts parsed from the evidence
    assert panel["advisory_nature"]["advisory"] is True
    assert "probability_percent" not in str(case)  # never a single percentage


async def test_detail_reports_the_changeset_count_basis(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 2, with_run=False)  # fixture 02 publishes its edit-time count
    case = (await client.get(f"{API}/cases/{seeded.case_id}")).json()
    user = case["changeset"]["user"]
    assert user["changesets_count_basis"] in {"edit_time", "current"}
    assert case["latest_run"] is None


async def test_unknown_and_malformed_ids_are_404_problems(client: httpx.AsyncClient) -> None:
    assert_problem(await client.get(f"{API}/cases/{uuid4()}"), 404, "not_found")
    assert_problem(await client.get(f"{API}/cases/not-a-uuid"), 404, "not_found")
    assert_problem(await client.get(f"{API}/cases/{uuid4()}/evidence"), 404, "not_found")
    assert_problem(await client.get(f"{API}/cases/{uuid4()}/runs"), 404, "not_found")
    assert_problem(await client.get(f"{API}/cases/{uuid4()}/audit"), 404, "not_found")


async def test_evidence_latest_by_id_and_other_case_is_404(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    one = await seed_case(factory, 1)
    two = await seed_case(factory, 2)
    latest = await client.get(f"{API}/cases/{one.case_id}/evidence")
    assert latest.status_code == 200
    evidence = latest.json()
    assert evidence["id"] == str(one.snapshot_id) and evidence["coverage"]["score"] <= 1
    assert evidence["rendered_text"]
    named = await client.get(
        f"{API}/cases/{one.case_id}/evidence", params={"snapshot_id": str(one.snapshot_id)}
    )
    assert named.status_code == 200
    foreign = await client.get(
        f"{API}/cases/{one.case_id}/evidence", params={"snapshot_id": str(two.snapshot_id)}
    )
    assert_problem(foreign, 404, "not_found")
    bare = await seed_bare_cases(factory, 1)
    assert_problem(await client.get(f"{API}/cases/{bare[0]}/evidence"), 404, "not_found")


async def test_runs_list_is_newest_first(client: httpx.AsyncClient, factory: Factory) -> None:
    seeded = await seed_case(factory, 1)
    from datetime import timedelta

    from api_support import BASE_TIME

    await seed_case(factory, 1, now=BASE_TIME + timedelta(hours=1))  # a second, newer run
    response = await client.get(f"{API}/cases/{seeded.case_id}/runs")
    items = response.json()["items"]
    assert len(items) == 2
    assert items[0]["created_at"] > items[1]["created_at"]
    assert str(seeded.run_id) in {item["id"] for item in items}


# --------------------------------------------------------------------------- queue


async def test_queue_orders_by_lane_and_counts_every_lane(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    await seed_case(factory, 1)  # looks consistent with reassuring readings
    await seed_case(factory, 4)  # a large deletion: policy rules fire
    body = (await client.get(f"{API}/cases")).json()
    assert set(body["counts_by_lane"]) == {lane.value for lane in Lane}
    assert sum(body["counts_by_lane"].values()) == 2
    ranks = [item["lane"] for item in body["items"]]
    assert ranks == sorted(
        ranks,
        key=lambda lane: [
            "review_suggested",
            "insufficient_evidence",
            "needs_local_knowledge",
            "rules_only",
            "looks_consistent",
        ].index(lane),
    )
    deleted = next(item for item in body["items"] if item["changeset_id"] == 900000000004)
    assert "R1" in deleted["flags"]  # policy rule codes join the OSMCha reason codes


async def test_queue_filters_and_counts_ignore_the_lane_filter(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    await seed_case(factory, 1)
    await seed_case(factory, 4)
    unfiltered = (await client.get(f"{API}/cases")).json()
    target = unfiltered["items"][0]["lane"]
    filtered = (await client.get(f"{API}/cases", params={"lane": target})).json()
    assert filtered["items"] and all(i["lane"] == target for i in filtered["items"])
    assert filtered["counts_by_lane"] == unfiltered["counts_by_lane"]
    by_id = (await client.get(f"{API}/cases", params={"q": "90000000000"})).json()
    assert {i["changeset_id"] for i in by_id["items"]} == {900000000001, 900000000004}
    none = (await client.get(f"{API}/cases", params={"stale": "true"})).json()
    assert none["items"] == []


async def test_bad_query_values_are_400(client: httpx.AsyncClient) -> None:
    for params in ({"lane": "nope"}, {"limit": 0}, {"limit": 101}, {"unknown": "x"}):
        assert_problem(await client.get(f"{API}/cases", params=params), 400, "validation_error")
    assert_problem(
        await client.get(f"{API}/cases", params={"cursor": "###"}), 400, "invalid_cursor"
    )
    assert_problem(
        await client.get(f"{API}/cases", params={"cursor": "YWJj"}), 400, "invalid_cursor"
    )


async def test_paging_is_stable_when_cases_are_inserted_between_pages(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    original = await seed_bare_cases(factory, 7)
    first = (await client.get(f"{API}/cases", params={"limit": 3})).json()
    assert len(first["items"]) == 3 and first["next_cursor"]

    # Two newer cases arrive while the reviewer is paging; they sort before the cursor.
    from datetime import timedelta

    from api_support import BASE_TIME

    await seed_bare_cases(
        factory, 2, first_changeset_id=900000200000, start=BASE_TIME + timedelta(hours=1)
    )
    seen = [item["id"] for item in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = (await client.get(f"{API}/cases", params={"limit": 3, "cursor": cursor})).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 7  # no repeats, no gaps, and none of the new rows
    assert set(seen) == {str(case_id) for case_id in original}
    fresh = (await client.get(f"{API}/cases", params={"limit": 100})).json()
    assert len(fresh["items"]) == 9


# --------------------------------------------------------------------------- audit


async def test_audit_lists_events_in_order_and_pages_by_cursor(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post(f"{API}/cases", json={"changeset_id": 900000000001})).json()
    case_id = created["case"]["id"]
    full = (await client.get(f"{API}/cases/{case_id}/audit")).json()
    actions = [event["action"] for event in full["items"]]
    assert actions == ["job.enqueued", "case.created"]
    assert [event["id"] for event in full["items"]] == sorted(e["id"] for e in full["items"])
    assert all(isinstance(event["id"], int) for event in full["items"])
    assert full["items"][0]["actor"] == "reviewer:Rae Reviewer"

    first = (await client.get(f"{API}/cases/{case_id}/audit", params={"limit": 1})).json()
    assert [e["action"] for e in first["items"]] == ["job.enqueued"] and first["next_cursor"]
    second = (
        await client.get(
            f"{API}/cases/{case_id}/audit", params={"limit": 1, "cursor": first["next_cursor"]}
        )
    ).json()
    assert [e["action"] for e in second["items"]] == ["case.created"]
    assert second["next_cursor"] is None


async def test_detail_text_from_osm_is_sanitized(
    client: httpx.AsyncClient, factory: Factory
) -> None:
    seeded = await seed_case(factory, 8)  # fixture 08: injection-style comment and markup
    case = (await client.get(f"{API}/cases/{seeded.case_id}")).json()
    comment = case["changeset"]["comment"]
    assert "<" not in comment and ">" not in comment
    evidence = (await client.get(f"{API}/cases/{seeded.case_id}/evidence")).json()
    for entry in evidence["discussion"]:
        assert "<" not in entry["text"] and "http://" not in entry["text"]

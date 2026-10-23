from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from cso.adapters.osm import MapRouletteClient, NotAllowedError, ParseError

URL = "https://maproulette.org/api/v2/challenge/55814/tasks"
UA = "ChangesetSecondOpinion/0.1 (+https://example.test; test@example.test)"


def task(task_id: int, status: int, changeset_id: object) -> dict[str, Any]:
    """Shape of a live MapRoulette task: the changeset id is a string in feature properties."""
    return {
        "id": task_id,
        "status": status,
        "changesetId": -1,
        "geometries": {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"changeset_id": changeset_id}}],
        },
    }


async def test_lists_tasks_with_the_documented_fields() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(URL).mock(
            return_value=httpx.Response(200, json=[task(1, 1, "183648026"), task(2, 2, 183633684)])
        )
        tasks = await MapRouletteClient(user_agent=UA).list_challenge_tasks(55814, limit=2)
        assert tasks == [
            {"changeset_id": 183648026, "status": 1, "task_id": 1},
            {"changeset_id": 183633684, "status": 2, "task_id": 2},
        ]
        request = route.calls.last.request
        assert request.url.params["limit"] == "2" and request.method == "GET"
        assert request.headers["user-agent"] == UA


async def test_skips_tasks_without_a_usable_changeset_id() -> None:
    payload: list[Any] = [
        task(1, 1, "not-a-number"),
        task(2, 1, ""),
        task(3, 1, "0"),
        {"id": 4, "status": 1, "geometries": None},
        {"id": "x", "status": 1, "geometries": task(9, 1, "5")["geometries"]},
        "garbage",
        task(5, 3, "77"),
    ]
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(return_value=httpx.Response(200, json=payload))
        tasks = await MapRouletteClient(user_agent=UA).list_challenge_tasks(55814)
    assert tasks == [{"changeset_id": 77, "status": 3, "task_id": 5}]


async def test_non_list_payload_is_a_parse_error() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(return_value=httpx.Response(200, json={"message": "nope"}))
        with pytest.raises(ParseError):
            await MapRouletteClient(user_agent=UA).list_challenge_tasks(55814)


async def test_limit_is_capped_and_arguments_validated() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(URL).mock(return_value=httpx.Response(200, json=[]))
        client = MapRouletteClient(user_agent=UA)
        await client.list_challenge_tasks(55814, limit=10_000)
        assert route.calls.last.request.url.params["limit"] == "1000"
        with pytest.raises(ValueError, match="positive"):
            await client.list_challenge_tasks(0)
        with pytest.raises(ValueError, match="positive"):
            await client.list_challenge_tasks(1, limit=0)


async def test_only_maproulette_host_is_reachable() -> None:
    client = MapRouletteClient(user_agent=UA)
    with pytest.raises(NotAllowedError):
        await client.request("GET", "https://api.openstreetmap.org/api/0.6/changeset/1.json")
    with pytest.raises(NotAllowedError):
        await client.request("POST", URL)


async def test_non_ascii_digits_and_oversized_ids_are_skipped_not_a_crash() -> None:
    """F-L7: `str.isdigit()` accepts these but `int()` raises; one bad task must not 500."""
    payload: list[Any] = [
        task(1, 1, "\u00b2"),  # superscript two
        task(2, 1, "\u0663"),  # Arabic-indic three
        task(3, 1, "1" * 20),
        task(4, 1, "\uff11\uff12"),  # fullwidth digits
        task(5, 1, "42"),
    ]
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(return_value=httpx.Response(200, json=payload))
        tasks = await MapRouletteClient(user_agent=UA).list_challenge_tasks(55814)
    assert tasks == [{"changeset_id": 42, "status": 1, "task_id": 5}]

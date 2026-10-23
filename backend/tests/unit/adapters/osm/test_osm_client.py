from __future__ import annotations

import anyio
import httpx
import pytest
import respx

from cso.adapters.osm import (
    BandwidthLimitError,
    NotAllowedError,
    NotFoundError,
    OsmClient,
    OsmTimeoutError,
    ParseError,
    RateLimitedError,
    Redacted403,
    SafeGetClient,
    TooLargeError,
    UpstreamError,
)
from cso.domain.enums import OsmType

BASE = "https://api.openstreetmap.org/api/0.6"
UA = "ChangesetSecondOpinion/0.1 (+https://example.test; test@example.test)"


class Sleeps:
    """Injectable sleep that records requested delays instead of waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_client(sleeps: Sleeps | None = None, **kwargs: object) -> OsmClient:
    return OsmClient(user_agent=UA, sleep=sleeps or Sleeps(), **kwargs)  # type: ignore[arg-type]


def element(osm_type: str, osm_id: int, version: int, **extra: object) -> dict[str, object]:
    return {"type": osm_type, "id": osm_id, "version": version, "tags": {}, **extra}


# ------------------------------------------------------------------ GET only and allowlist


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "post"])
async def test_non_get_methods_are_refused_without_a_request(method: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.route().mock(return_value=httpx.Response(200, json={}))
        client = make_client()
        with pytest.raises(NotAllowedError):
            await client.request(method, f"{BASE}/changeset/1.json")
        assert not route.called
        assert client.calls == 0 and client.http_attempts == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/api/0.6/changeset/1.json",
        "https://www.openstreetmap.org/api/0.6/changeset/1.json",
        "https://api.openstreetmap.org.evil.example/x",
        "https://api.openstreetmap.org@evil.example/x",
        "https://user:pw@api.openstreetmap.org/x",
        "http://api.openstreetmap.org/api/0.6/changeset/1.json",
        "https://api.openstreetmap.org:8443/api/0.6/changeset/1.json",
        "ftp://api.openstreetmap.org/x",
        "https://maproulette.org/api/v2/challenge/1/tasks",
    ],
)
async def test_off_allowlist_urls_are_refused(url: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.route().mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(NotAllowedError):
            await make_client().request("GET", url)
        assert not route.called


async def test_allowlist_is_configurable_but_exact() -> None:
    client = SafeGetClient(allowed_hosts=frozenset({"maproulette.org"}), user_agent=UA)
    with pytest.raises(NotAllowedError):
        await client.request("GET", f"{BASE}/changeset/1.json")
    await client.aclose()


async def test_redirect_off_allowlist_is_refused_not_followed() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/changeset/1.json").mock(
            return_value=httpx.Response(302, headers={"Location": "https://evil.example/steal"})
        )
        evil = router.get("https://evil.example/steal").mock(return_value=httpx.Response(200))
        with pytest.raises(NotAllowedError):
            await make_client().get_changeset(1)
        assert not evil.called


async def test_redirect_within_allowlist_is_followed_and_rechecked() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/changeset/1.json").mock(
            return_value=httpx.Response(301, headers={"Location": "/api/0.6/changeset/2.json"})
        )
        router.get(f"{BASE}/changeset/2.json").mock(
            return_value=httpx.Response(200, json={"changeset": {"id": 2}})
        )
        client = make_client()
        assert (await client.get_changeset(1))["changeset"]["id"] == 2
        assert client.calls == 1 and client.http_attempts == 2


async def test_redirect_loop_is_bounded() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/changeset/1.json").mock(
            return_value=httpx.Response(302, headers={"Location": f"{BASE}/changeset/1.json"})
        )
        with pytest.raises(NotAllowedError, match="redirects"):
            await make_client().get_changeset(1)


async def test_user_agent_and_query_are_sent() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/changeset/7.json").mock(
            return_value=httpx.Response(200, json={"changeset": {"id": 7}})
        )
        await make_client().get_changeset(7)
        request = route.calls.last.request
        assert request.headers["user-agent"] == UA
        assert request.url.params["include_discussion"] == "true"
        assert request.method == "GET"


# ------------------------------------------------------------------ retries, errors, caps


async def test_backoff_1_2_4_on_5xx_then_success() -> None:
    sleeps = Sleeps()
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/user/5.json").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(502),
                httpx.Response(500),
                httpx.Response(200, json={"user": {"id": 5}}),
            ]
        )
        client = make_client(sleeps)
        assert (await client.get_user(5))["user"]["id"] == 5
        assert route.call_count == 4
    assert sleeps.delays == [1.0, 2.0, 4.0]
    assert client.calls == 1 and client.http_attempts == 4


async def test_retries_exhausted_raise_typed_errors() -> None:
    sleeps = Sleeps()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/user/5.json").mock(return_value=httpx.Response(429))
        router.get(f"{BASE}/user/6.json").mock(return_value=httpx.Response(503))
        with pytest.raises(RateLimitedError):
            await make_client(sleeps).get_user(5)
        with pytest.raises(UpstreamError) as info:
            await make_client(sleeps).get_user(6)
        assert info.value.status == 503 and not isinstance(info.value, RateLimitedError)


async def test_509_stops_without_retry() -> None:
    sleeps = Sleeps()
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/user/5.json").mock(return_value=httpx.Response(509))
        with pytest.raises(BandwidthLimitError):
            await make_client(sleeps).get_user(5)
        assert route.call_count == 1
    assert sleeps.delays == []


@pytest.mark.parametrize(
    ("status", "error"),
    [(403, Redacted403), (404, NotFoundError), (410, NotFoundError), (400, UpstreamError)],
)
async def test_status_mapping_does_not_retry(status: int, error: type[Exception]) -> None:
    sleeps = Sleeps()
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/node/1/2.json").mock(return_value=httpx.Response(status))
        with pytest.raises(error):
            await make_client(sleeps).get_element_version(OsmType.NODE, 1, 2)
        assert route.call_count == 1
    assert sleeps.delays == []


async def test_timeout_maps_to_typed_error() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/user/5.json").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(OsmTimeoutError):
            await make_client().get_user(5)


async def test_transport_error_maps_to_upstream_error() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/user/5.json").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(UpstreamError):
            await make_client().get_user(5)


async def test_declared_oversize_response_is_rejected() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/changeset/1/download").mock(
            return_value=httpx.Response(200, content=b"x" * 2048)
        )
        with pytest.raises(TooLargeError) as info:
            await make_client(max_bytes=1024).get_osc(1)
        assert info.value.limit == 1024


async def test_undeclared_oversize_stream_is_cut_off() -> None:
    async def chunks() -> object:
        for _ in range(10):
            yield b"y" * 512

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/changeset/1/download").mock(
            return_value=httpx.Response(200, content=chunks())
        )
        with pytest.raises(TooLargeError):
            await make_client(max_bytes=1024).get_osc(1)


async def test_invalid_json_is_a_parse_error() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/user/5.json").mock(return_value=httpx.Response(200, content=b"<html>"))
        with pytest.raises(ParseError):
            await make_client().get_user(5)


async def test_at_most_two_requests_in_flight() -> None:
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await anyio.sleep(0.02)
        in_flight -= 1
        return httpx.Response(200, json={"user": {"id": 1}})

    with respx.mock(assert_all_called=False) as router:
        router.get(host="api.openstreetmap.org").mock(side_effect=handler)
        client = make_client()
        async with anyio.create_task_group() as tg:
            for uid in range(1, 9):
                tg.start_soon(client.get_user, uid)
    assert peak == 2


# ------------------------------------------------------------------ endpoint helpers


async def test_get_osc_returns_bytes() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/changeset/9/download").mock(
            return_value=httpx.Response(200, content=b"<osmChange/>")
        )
        assert await make_client().get_osc(9) == b"<osmChange/>"
        assert route.calls.last.request.headers["accept"] == "application/xml"


async def test_get_element_version_returns_single_element_and_validates_match() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/way/10/3.json").mock(
            return_value=httpx.Response(200, json={"elements": [element("way", 10, 3)]})
        )
        router.get(f"{BASE}/way/11/3.json").mock(
            return_value=httpx.Response(200, json={"elements": [element("way", 99, 3)]})
        )
        router.get(f"{BASE}/way/12/3.json").mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        client = make_client()
        assert (await client.get_element_version(OsmType.WAY, 10, 3))["version"] == 3
        with pytest.raises(ParseError):
            await client.get_element_version(OsmType.WAY, 11, 3)
        with pytest.raises(ParseError):
            await client.get_element_version(OsmType.WAY, 12, 3)


async def test_history_is_sorted_ascending() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/node/5/history.json").mock(
            return_value=httpx.Response(
                200, json={"elements": [element("node", 5, 3), element("node", 5, 1)]}
            )
        )
        history = await make_client().get_element_history(OsmType.NODE, 5)
        assert [e["version"] for e in history] == [1, 3]


async def test_multi_fetch_all_or_nothing_and_cap() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE}/nodes.json").mock(
            return_value=httpx.Response(
                200, json={"elements": [element("node", 1, 1), element("node", 2, 1)]}
            )
        )
        client = make_client()
        got = await client.get_elements(OsmType.NODE, [2, 1, 2])
        assert sorted(got) == [1, 2]
        assert route.calls.last.request.url.params["nodes"] == "1,2"
        with pytest.raises(NotFoundError):
            await client.get_elements(OsmType.NODE, [1, 2, 3])
        with pytest.raises(ValueError, match="at most 200"):
            await client.get_elements(OsmType.NODE, list(range(1, 202)))
        assert await client.get_elements(OsmType.NODE, []) == {}


@pytest.mark.parametrize("bad", [0, -1, True])
async def test_ids_must_be_positive_integers(bad: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        await make_client().get_changeset(bad)

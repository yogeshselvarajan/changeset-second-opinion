"""Rate limits (429 with Retry-After) and the security headers on API responses."""

from __future__ import annotations

from pathlib import Path

import httpx
from auth_support import build_env, client_for, csrf, login_as, mint_invite

from cso.api.security import CSP, RateLimiter, retry_after_headers


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ------------------------------------------------------------------------------ limiter unit


def test_bucket_allows_the_capacity_then_says_how_long_to_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    assert [limiter.hit("k", capacity=3, window_s=60) for _ in range(3)] == [None, None, None]
    wait = limiter.hit("k", capacity=3, window_s=60)
    assert wait is not None and 19.0 < wait <= 20.0  # one token per 20 s


def test_bucket_refills_over_time_and_keys_are_independent() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    for _ in range(3):
        limiter.hit("a", capacity=3, window_s=60)
    assert limiter.hit("a", capacity=3, window_s=60) is not None
    assert limiter.hit("b", capacity=3, window_s=60) is None
    clock.now += 21
    assert limiter.hit("a", capacity=3, window_s=60) is None  # one token came back
    assert limiter.hit("a", capacity=3, window_s=60) is not None
    clock.now += 600
    assert [limiter.hit("a", capacity=3, window_s=60) for _ in range(3)] == [None] * 3


def test_limiter_forgets_old_keys_instead_of_growing_forever() -> None:
    limiter = RateLimiter(clock=FakeClock(), max_keys=50)
    for i in range(500):
        limiter.hit(f"k{i}", capacity=1, window_s=60)
    assert len(limiter._state) <= 50  # noqa: SLF001


def test_retry_after_is_whole_seconds_and_at_least_one() -> None:
    assert retry_after_headers(0.2) == {"Retry-After": "1"}
    assert retry_after_headers(19.01) == {"Retry-After": "20"}


# ------------------------------------------------------------------------------ over HTTP


def _assert_rate_limited(response: httpx.Response) -> None:
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert int(response.headers["retry-after"]) >= 1
    body = response.json()
    assert body["type"] == "urn:cso:problem:rate_limited" and body["status"] == 429
    assert body["request_id"]


async def test_login_attempts_are_limited_per_ip(tmp_path: Path) -> None:
    async with build_env(tmp_path, login_attempts=3) as env, client_for(env) as client:
        for _ in range(3):
            assert (await login_as(client, "cso-00000000-" + "a" * 32)).status_code == 401
        _assert_rate_limited(await login_as(client, await mint_invite(env)))


async def test_a_forwarded_for_header_is_ignored_unless_the_proxy_is_trusted(
    tmp_path: Path,
) -> None:
    bad = "cso-00000000-" + "a" * 32
    async with build_env(tmp_path, login_attempts=2) as env, client_for(env) as client:
        for i in range(2):
            await client.post(
                "/api/v1/auth/login",
                json={"invite_code": bad, "display_name": "x"},
                headers={"X-Forwarded-For": f"9.9.9.{i}"},
            )
        spoofed = await client.post(
            "/api/v1/auth/login",
            json={"invite_code": bad, "display_name": "x"},
            headers={"X-Forwarded-For": "9.9.9.99"},
        )
        _assert_rate_limited(spoofed)  # spoofing the header did not buy a fresh bucket

    (tmp_path / "t").mkdir()
    async with build_env(tmp_path / "t", login_attempts=2, trust_proxy=True) as env2:
        async with client_for(env2) as client:
            for i in range(4):
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"invite_code": bad, "display_name": "x"},
                    headers={"X-Forwarded-For": f"203.0.113.7, 10.0.0.{i}"},
                )
                assert response.status_code in {401, 429}
            same_client = await client.post(
                "/api/v1/auth/login",
                json={"invite_code": bad, "display_name": "x"},
                headers={"X-Forwarded-For": "198.51.100.1, 10.0.0.1"},
            )
            assert same_client.status_code == 401  # a different rightmost hop is a different bucket


async def test_anonymous_analysis_quota_is_per_ip(tmp_path: Path) -> None:
    async with build_env(tmp_path, analysis_per_ip_hour=3, trust_proxy=True) as env:
        async with client_for(env) as client:
            hop = {"X-Forwarded-For": "10.1.1.1"}
            for _ in range(3):
                assert (await client.post("/api/v1/analyze-anon", headers=hop)).status_code == 200
            _assert_rate_limited(await client.post("/api/v1/analyze-anon", headers=hop))
            other = {"X-Forwarded-For": "10.2.2.2"}
            assert (await client.post("/api/v1/analyze-anon", headers=other)).status_code == 200


async def test_session_analysis_quota_is_per_session(tmp_path: Path) -> None:
    async with build_env(tmp_path, analysis_per_session_day=2) as env:
        code = await mint_invite(env)
        async with client_for(env) as a, client_for(env) as b:
            await login_as(a, code, "a")
            await login_as(b, code, "b")
            for _ in range(2):
                assert (await a.post("/api/v1/analyze", headers=csrf(a))).status_code == 200
            _assert_rate_limited(await a.post("/api/v1/analyze", headers=csrf(a)))
            assert (await b.post("/api/v1/analyze", headers=csrf(b))).status_code == 200


async def test_mutations_are_flood_limited_per_ip(tmp_path: Path) -> None:
    async with build_env(tmp_path, mutations_per_ip_minute=3) as env, client_for(env) as client:
        for _ in range(3):
            assert (await client.post("/api/v1/analyze-anon")).status_code == 200
        _assert_rate_limited(await client.post("/api/v1/analyze-anon"))
        assert (await client.get("/api/v1/ping")).status_code == 200  # reads are not counted


# ------------------------------------------------------------------------------ headers


async def test_security_headers_are_on_every_kind_of_api_response(tmp_path: Path) -> None:
    async with build_env(tmp_path, mutations_per_ip_minute=2) as env, client_for(env) as client:
        responses = [
            await client.get("/api/v1/ping"),  # 200
            await client.post("/api/v1/write"),  # 401 problem
            await client.get("/api/v1/does-not-exist"),  # 404 problem
            await client.post("/api/v1/open"),  # 200 (counts toward the flood limit)
            await client.post("/api/v1/open"),  # 429 problem from the middleware
        ]
        assert [r.status_code for r in responses] == [200, 401, 404, 200, 429]
        for response in responses:
            assert response.headers["content-security-policy"] == CSP
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["x-frame-options"] == "DENY"


def test_csp_is_the_policy_from_the_security_doc() -> None:
    for directive in (
        "default-src 'self'",
        "connect-src 'self' https://tiles.openfreemap.org",
        "img-src 'self' data: blob:",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self'",
        "worker-src 'self' blob:",
        "child-src 'self' blob:",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
    ):
        assert directive in CSP


async def test_identity_responses_are_not_cached(tmp_path: Path) -> None:
    async with build_env(tmp_path) as env, client_for(env) as client:
        assert (await client.get("/api/v1/me")).headers["cache-control"] == "no-store"
        login = await login_as(client, await mint_invite(env))
        assert login.headers["cache-control"] == "no-store"
        assert "cache-control" not in (await client.get("/api/v1/ping")).headers

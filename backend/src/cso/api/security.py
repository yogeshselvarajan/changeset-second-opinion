"""Security headers, cross-origin and CSRF checks, and rate limits.

Rate limits are in-process token buckets: they reset on restart and are not shared between
processes. That is acceptable for the single-host MVP (one API process, <=5 reviewers); a second
API process or a database or Redis backed limiter is the growth path. Caddy's per-IP request limit
sits in front of this one.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cso.api.auth_core import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SAFE_METHODS,
    SESSION_COOKIE,
    AuthConfig,
    CrossOriginError,
    CsrfError,
    client_ip,
    constant_time_equals,
    get_config,
)
from cso.api.deps import Principal, get_optional_principal
from cso.api.problems import (
    ApiError,
    RateLimitedError,
    get_request_id,
    problem_from_api_error,
    problem_response,
)

CSP = (
    "default-src 'self'; connect-src 'self' https://tiles.openfreemap.org; "
    "img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "worker-src 'self' blob:; child-src 'self' blob:; "
    "object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
NO_STORE_PREFIXES = ("/api/v1/auth/", "/api/v1/me")
LOGIN_PATH = "/api/v1/auth/login"


# --------------------------------------------------------------------------- rate limiting


class RateLimiter:
    """Token buckets keyed by string. `hit` returns None when allowed, else seconds to wait."""

    def __init__(
        self, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 20_000
    ) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._state: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def hit(self, key: str, *, capacity: int, window_s: float, cost: int = 1) -> float | None:
        """Consume `cost` tokens; the bucket holds `capacity` and refills `capacity` per window.

        Nothing is consumed when the bucket cannot pay the whole cost.
        """
        now = self._clock()
        rate = capacity / window_s
        tokens, last = self._state.get(key, (float(capacity), now))
        tokens = min(float(capacity), tokens + (now - last) * rate)
        if tokens < cost:
            self._state[key] = (tokens, now)
            self._state.move_to_end(key)
            return (cost - tokens) / rate
        self._state[key] = (tokens - cost, now)
        self._state.move_to_end(key)
        while len(self._state) > self._max_keys:
            self._state.popitem(last=False)  # forget the least recently used key
        return None


def get_limiter(app: FastAPI) -> RateLimiter:
    """The app's RateLimiter (set by `install_security`), created on first use otherwise."""
    limiter = getattr(app.state, "rate_limiter", None)
    if not isinstance(limiter, RateLimiter):
        limiter = RateLimiter()
        app.state.rate_limiter = limiter
    return limiter


def retry_after_headers(wait_s: float) -> dict[str, str]:
    """`Retry-After` in whole seconds, at least 1."""
    return {"Retry-After": str(max(1, math.ceil(wait_s)))}


def charge_quota(request: Request, principal: Principal, bucket: str, cost: int = 1) -> None:
    """Take `cost` tokens from the caller's `bucket` quota; raises 429 with Retry-After."""
    config = get_config(request)
    if principal.anonymous:
        key = f"{bucket}:ip:{client_ip(request, config)}"
        capacity, window = config.analysis_per_ip_hour, 3600.0
    else:
        key = f"{bucket}:session:{principal.id}"
        capacity, window = config.analysis_per_session_day, 86400.0
    wait = get_limiter(request.app).hit(key, capacity=capacity, window_s=window, cost=cost)
    if wait is not None:
        raise RateLimitedError(
            "Too many requests; try again later.", headers=retry_after_headers(wait)
        )


def quota(bucket: str) -> Callable[..., Awaitable[None]]:
    """Dependency factory for expensive actions: 10/hour per IP unauthenticated, 60/day per session.

    `Depends(quota("analysis"))` on POST /cases, POST /cases/{id}/analyses and the import
    endpoint; `Depends(quota("draft"))` on draft requests. Raises 429 with Retry-After. It takes
    one token; the import endpoint charges the remaining tokens once it knows how many analyses it
    will queue (`charge_quota`). Routes list the role check BEFORE this dependency so a caller
    without the role is refused before a token is taken.
    """

    async def dependency(
        request: Request,
        principal: Principal = Depends(get_optional_principal),  # noqa: B008
    ) -> None:
        charge_quota(request, principal, bucket)

    return dependency


analysis_quota = quota("analysis")
draft_quota = quota("draft")


# --------------------------------------------------------------------------- middleware


def _reject(request: Request, error: ApiError) -> Response:
    problem = problem_from_api_error(
        error, request_id=get_request_id(request), instance=request.url.path
    )
    return problem_response(problem, error.headers)


class SecurityMiddleware:
    """Headers on every response; origin, CSRF and flood checks on non-GET requests under /api.

    Pure ASGI (not BaseHTTPMiddleware) so streaming responses and exceptions behave. Errors it
    raises are returned directly as problem+json, because exception handlers do not see them.
    """

    def __init__(
        self, app: ASGIApp, *, config: AuthConfig | None = None, limiter: RateLimiter | None = None
    ) -> None:
        self.app = app
        self._config = config
        self._limiter = limiter

    def _cfg(self, scope: Scope) -> AuthConfig:
        if self._config is not None:
            return self._config
        return get_config(Request(scope))

    def _lim(self, scope: Scope) -> RateLimiter:
        return self._limiter if self._limiter is not None else get_limiter(scope["app"])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        no_store = path.startswith(NO_STORE_PREFIXES)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = dict(SECURITY_HEADERS)
                if no_store:
                    extra["Cache-Control"] = "no-store"
                headers = list(message.get("headers", []))
                for name, value in extra.items():
                    if name.lower().encode() not in present:
                        headers.append((name.lower().encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        if scope["method"] not in SAFE_METHODS and path.startswith("/api"):
            request = Request(scope)
            error = self._check_unsafe(request, scope, path)
            if error is not None:
                await _reject(request, error)(scope, receive, send_with_headers)
                return
        await self.app(scope, receive, send_with_headers)

    def _check_unsafe(self, request: Request, scope: Scope, path: str) -> ApiError | None:
        config = self._cfg(scope)
        expected_host = request.headers.get("host", "").lower()
        if config.trust_proxy:
            expected_host = request.headers.get("x-forwarded-host", expected_host).lower()

        origin = request.headers.get("origin")
        if origin is not None and (
            origin == "null" or urlsplit(origin).netloc.lower() != expected_host
        ):
            return CrossOriginError("Cross-origin requests are not accepted.")
        if request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}:
            return CrossOriginError("Cross-site requests are not accepted.")

        # Double-submit: when a session cookie is present, `X-CSRF` must equal the CSRF cookie.
        # The binding to the session itself is checked in `deps.get_optional_principal`. Login
        # is exempt (it has no session yet, and a stale cookie must not block signing in again).
        if path != LOGIN_PATH and request.cookies.get(SESSION_COOKIE):
            header = request.headers.get(CSRF_HEADER)
            cookie = request.cookies.get(CSRF_COOKIE)
            if not header or not cookie or not constant_time_equals(header, cookie):
                return CsrfError("The X-CSRF header is required for this request.")

        wait = self._lim(scope).hit(
            f"mutation:ip:{client_ip(request, config)}",
            capacity=config.mutations_per_ip_minute,
            window_s=60.0,
        )
        if wait is not None:
            return RateLimitedError(
                "Too many requests; try again later.", headers=retry_after_headers(wait)
            )
        return None


def install_security(
    app: FastAPI,
    *,
    config: AuthConfig | None = None,
    limiter: RateLimiter | None = None,
) -> None:
    """Attach auth config, the rate limiter and `SecurityMiddleware` to the app.

    Call once while building the app, after `install_problem_handlers`. Also set
    `app.state.session_factory` (an `async_sessionmaker`) so sessions can be resolved.
    """
    if config is not None:
        app.state.auth_config = config
    app.state.rate_limiter = limiter or RateLimiter()
    app.add_middleware(SecurityMiddleware)

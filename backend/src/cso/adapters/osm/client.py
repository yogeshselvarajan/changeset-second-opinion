"""GET-only, allowlisted HTTP access (SafeGetClient) and the live OSM API client (OsmClient)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx

from cso.adapters.osm.errors import (
    BandwidthLimitError,
    NotAllowedError,
    NotFoundError,
    OsmTimeoutError,
    ParseError,
    RateLimitedError,
    Redacted403,
    TooLargeError,
    UpstreamError,
)
from cso.adapters.osm.protocol import MAX_MULTIFETCH_IDS
from cso.domain.enums import OsmType
from cso.settings import Settings

OSM_API_HOST = "api.openstreetmap.org"
OSM_API_BASE = f"https://{OSM_API_HOST}/api/0.6"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
CALL_TIMEOUT_S = 8.0
BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0)
MAX_CONCURRENCY = 2
MAX_REDIRECTS = 3
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

type Sleep = Callable[[float], Awaitable[None]]


class SafeGetClient:
    """Shared HTTP guard: the only code in this package that talks to the network.

    `request()` is the single choke point: it refuses any method but GET and any URL whose scheme
    is not https or whose host is not on the allowlist, follows redirects manually (each hop is
    re-checked), keeps at most `concurrency` requests in flight, retries 429/5xx with backoff, and
    reads bodies as a stream with a hard byte cap.
    """

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        user_agent: str,
        http: httpx.AsyncClient | None = None,
        timeout_s: float = CALL_TIMEOUT_S,
        max_bytes: int = MAX_RESPONSE_BYTES,
        backoff_s: Sequence[float] = BACKOFF_S,
        sleep: Sleep = anyio.sleep,
        concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        self._allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self._user_agent = user_agent
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            follow_redirects=False, timeout=httpx.Timeout(timeout_s)
        )
        self._max_bytes = max_bytes
        self._backoff_s = tuple(backoff_s)
        self._sleep = sleep
        self._limiter = anyio.CapacityLimiter(concurrency)
        self.calls = 0  # logical calls (one per request(); retries and redirects excluded)
        self.http_attempts = 0  # HTTP requests actually sent

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance created it."""
        if self._owns_http:
            await self._http.aclose()

    def _check_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise NotAllowedError(f"scheme not allowed: {parts.scheme!r}")
        if parts.username is not None or parts.password is not None:
            raise NotAllowedError("credentials in URL are not allowed")
        host = (parts.hostname or "").lower()
        if host not in self._allowed_hosts:
            raise NotAllowedError(f"host not on allowlist: {host!r}")
        if parts.port not in (None, 443):
            raise NotAllowedError(f"port not allowed: {parts.port}")

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        accept: str = "application/json",
    ) -> bytes:
        """Perform a GET and return the capped body; any other method raises NotAllowedError."""
        if method.upper() != "GET":
            raise NotAllowedError(f"only GET is allowed, got {method!r}")
        self._check_url(url)
        self.calls += 1
        current, current_params = url, params
        for _hop in range(MAX_REDIRECTS + 1):
            result = await self._get_with_retries(current, current_params, accept)
            if isinstance(result, bytes):
                return result
            self._check_url(result)  # off-list redirects are refused, never followed
            current, current_params = result, None
        raise NotAllowedError(f"too many redirects (>{MAX_REDIRECTS})")

    async def get_json(
        self, url: str, *, params: dict[str, str] | None = None
    ) -> dict[str, Any] | list[Any]:
        """GET and decode JSON; ParseError on invalid JSON."""
        body = await self.request("GET", url, params=params)
        try:
            data: dict[str, Any] | list[Any] = json.loads(body)
        except ValueError as exc:
            raise ParseError(f"invalid JSON from {urlsplit(url).path}: {exc}") from exc
        return data

    async def _get_with_retries(
        self, url: str, params: dict[str, str] | None, accept: str
    ) -> bytes | str:
        """Return the body, or the absolute redirect target (str) for a 3xx."""
        last_status = 0
        for attempt in range(len(self._backoff_s) + 1):
            result = await self._attempt(url, params, accept)
            if not isinstance(result, int):
                return result
            last_status = result
            if attempt < len(self._backoff_s):
                await self._sleep(self._backoff_s[attempt])
        message = f"HTTP {last_status} from {urlsplit(url).path} after retries"
        if last_status == 429:
            raise RateLimitedError(message, status=429)
        raise UpstreamError(message, status=last_status)

    async def _attempt(
        self, url: str, params: dict[str, str] | None, accept: str
    ) -> bytes | str | int:
        """One HTTP exchange. Returns body, redirect URL, or a retryable status code."""
        headers = {"User-Agent": self._user_agent, "Accept": accept}
        path = urlsplit(url).path
        status = 0
        async with self._limiter:
            self.http_attempts += 1
            try:
                async with self._http.stream(
                    "GET", url, params=params, headers=headers, follow_redirects=False
                ) as resp:
                    status = resp.status_code
                    if status == 200:
                        return await self._read_capped(resp)
                    if status in _REDIRECT_STATUSES:
                        location = resp.headers.get("location")
                        if not location:
                            raise UpstreamError(f"redirect without Location: {path}", status=status)
                        return str(resp.url.join(location))
            except httpx.TimeoutException as exc:
                raise OsmTimeoutError(f"timeout calling {path}") from exc
            except httpx.HTTPError as exc:
                raise UpstreamError(f"transport error calling {path}: {exc!r}") from exc
        if status in (404, 410):
            raise NotFoundError(f"HTTP {status} for {path}")
        if status == 403:
            raise Redacted403(f"HTTP 403 for {path}")
        if status == 509:
            raise BandwidthLimitError(f"HTTP 509 bandwidth limit on {path}", status=509)
        if status == 429 or 500 <= status < 600:
            return status
        raise UpstreamError(f"HTTP {status} for {path}", status=status)

    async def _read_capped(self, resp: httpx.Response) -> bytes:
        declared = resp.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            raise TooLargeError(f"response declares {declared} bytes", limit=self._max_bytes)
        buf = bytearray()
        async for chunk in resp.aiter_bytes():  # decoded bytes, so inflating bodies are capped too
            buf += chunk
            if len(buf) > self._max_bytes:
                raise TooLargeError("response exceeds byte cap", limit=self._max_bytes)
        return bytes(buf)


def _positive(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return value


def _as_dict(data: object, what: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ParseError(f"{what}: expected a JSON object")
    return data


def _elements(data: object, what: str) -> list[dict[str, Any]]:
    items = _as_dict(data, what).get("elements")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ParseError(f"{what}: 'elements' must be a list of objects")
    return items


class OsmClient(SafeGetClient):
    """Live, read-only OSM API 0.6 client implementing the OsmSource protocol."""

    def __init__(
        self,
        *,
        user_agent: str,
        http: httpx.AsyncClient | None = None,
        base_url: str = OSM_API_BASE,
        sleep: Sleep = anyio.sleep,
        timeout_s: float = CALL_TIMEOUT_S,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        super().__init__(
            allowed_hosts=frozenset({OSM_API_HOST}),
            user_agent=user_agent,
            http=http,
            sleep=sleep,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
        )
        self._base = base_url.rstrip("/")

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> OsmClient:
        """Build a client using the configured User-Agent."""
        return cls(user_agent=settings.user_agent, **kwargs)

    async def get_changeset(self, changeset_id: int) -> dict[str, Any]:
        """GET changeset/{id}.json?include_discussion=true."""
        cid = _positive("changeset_id", changeset_id)
        data = await self.get_json(
            f"{self._base}/changeset/{cid}.json", params={"include_discussion": "true"}
        )
        return _as_dict(data, "changeset.json")

    async def get_osc(self, changeset_id: int) -> bytes:
        """GET changeset/{id}/download (osmChange XML)."""
        cid = _positive("changeset_id", changeset_id)
        return await self.request(
            "GET", f"{self._base}/changeset/{cid}/download", accept="application/xml"
        )

    async def get_element_version(
        self, osm_type: OsmType, osm_id: int, version: int
    ) -> dict[str, Any]:
        """GET {type}/{id}/{version}.json and return its single element."""
        oid, ver = _positive("osm_id", osm_id), _positive("version", version)
        data = await self.get_json(f"{self._base}/{osm_type.value}/{oid}/{ver}.json")
        items = _elements(data, "element version")
        if len(items) != 1:
            raise ParseError(f"element version: expected 1 element, got {len(items)}")
        el = items[0]
        if (el.get("type"), el.get("id"), el.get("version")) != (osm_type.value, oid, ver):
            raise ParseError("element version: response does not match the request")
        return el

    async def get_element_history(self, osm_type: OsmType, osm_id: int) -> list[dict[str, Any]]:
        """GET {type}/{id}/history.json, ascending by version."""
        oid = _positive("osm_id", osm_id)
        data = await self.get_json(f"{self._base}/{osm_type.value}/{oid}/history.json")
        items = _elements(data, "element history")
        try:
            return sorted(items, key=lambda e: int(e["version"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ParseError("element history: element without integer version") from exc

    async def get_elements(
        self, osm_type: OsmType, osm_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        """GET {type}s.json?{type}s=1,2,3; all-or-nothing (404 if any id is missing)."""
        ids = sorted({_positive("osm_id", i) for i in osm_ids})
        if not ids:
            return {}
        if len(ids) > MAX_MULTIFETCH_IDS:
            raise ValueError(f"at most {MAX_MULTIFETCH_IDS} ids per call, got {len(ids)}")
        plural = f"{osm_type.value}s"
        data = await self.get_json(
            f"{self._base}/{plural}.json", params={plural: ",".join(map(str, ids))}
        )
        found: dict[int, dict[str, Any]] = {}
        for el in _elements(data, "multi-fetch"):
            el_id = el.get("id")
            if isinstance(el_id, int):
                found[el_id] = el
        missing = [i for i in ids if i not in found]
        if missing:
            raise NotFoundError(f"multi-fetch missing ids: {missing[:5]}")
        return found

    async def get_user(self, uid: int) -> dict[str, Any]:
        """GET user/{uid}.json."""
        data = await self.get_json(f"{self._base}/user/{_positive('uid', uid)}.json")
        return _as_dict(data, "user.json")

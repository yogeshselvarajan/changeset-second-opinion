"""HTTP client for `strands-decider serve` (`GET /health`, `POST /v1/systemone`), sync and async."""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_TIMEOUT_S = 45.0  # GPU; use 90 for CPU
_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError)


class DeciderError(Exception):
    """Base class for transport-level failures."""


class DeciderUnavailable(DeciderError):
    """Connection failure, timeout or an unexpected HTTP status."""


class StateTooLong(DeciderError):
    """HTTP 422: the server rejected the request. Never retried."""


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise DeciderUnavailable(f"non-JSON response (HTTP {response.status_code})") from exc


def _handle(response: httpx.Response) -> Any:
    if response.status_code == 422:
        raise StateTooLong(response.text[:500])
    if response.status_code != 200:
        raise DeciderUnavailable(f"HTTP {response.status_code}")
    return _json(response)


class DeciderClient:
    """Synchronous client. One retry on connection errors, none on 422 or timeouts."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url, timeout=httpx.Timeout(timeout_s, connect=3.0), transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def health(self) -> dict[str, Any]:
        """Identity of the running model."""
        return self._request("GET", "/health", None)

    def systemone(self, request: dict[str, Any]) -> Any:
        """POST the request and return the parsed JSON, unvalidated."""
        return self._request("POST", "/v1/systemone", request)

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        for attempt in (1, 2):
            try:
                return _handle(self._http.request(method, path, json=body))
            except _RETRYABLE as exc:
                if attempt == 2:
                    raise DeciderUnavailable(f"connection failed: {exc!r}") from exc
            except httpx.TimeoutException as exc:
                raise DeciderUnavailable(f"timeout: {exc!r}") from exc
            except httpx.HTTPError as exc:
                raise DeciderUnavailable(f"transport error: {exc!r}") from exc
        raise AssertionError("unreachable")


class AsyncDeciderClient:
    """Asynchronous client with the same behaviour as `DeciderClient`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout_s, connect=3.0), transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> dict[str, Any]:
        """Identity of the running model."""
        return await self._request("GET", "/health", None)

    async def systemone(self, request: dict[str, Any]) -> Any:
        """POST the request and return the parsed JSON, unvalidated."""
        return await self._request("POST", "/v1/systemone", request)

    async def _request(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        for attempt in (1, 2):
            try:
                return _handle(await self._http.request(method, path, json=body))
            except _RETRYABLE as exc:
                if attempt == 2:
                    raise DeciderUnavailable(f"connection failed: {exc!r}") from exc
            except httpx.TimeoutException as exc:
                raise DeciderUnavailable(f"timeout: {exc!r}") from exc
            except httpx.HTTPError as exc:
                raise DeciderUnavailable(f"transport error: {exc!r}") from exc
        raise AssertionError("unreachable")

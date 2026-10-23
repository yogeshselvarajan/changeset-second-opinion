"""Sign in with OpenStreetMap: the authorization-code exchange and the one profile read.

This is the only module that may POST, and it POSTs to exactly one URL: the OSM token endpoint,
`TOKEN_URL`, to trade an authorization code for an access token. The scope asked for is
`read_prefs` and nothing else, so the token cannot change anything on the map. The token is used
once, for a GET of the signed-in user's own details, and is never stored or logged.

`scripts/ci/check_no_osm_writes.py` knows this module by name: it allows one `post` call whose URL
is the constant `TOKEN_URL` and refuses every other write call here, and it refuses the token
path in any other file. Keep it that way: a second POST needs a change to the CI script, an ADR
and the owner's sign-off.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://www.openstreetmap.org/oauth2/authorize"
TOKEN_URL = "https://www.openstreetmap.org/oauth2/token"  # noqa: S105 (a URL, not a secret)
USER_DETAILS_URL = "https://api.openstreetmap.org/api/0.6/user/details.json"
SCOPE = "read_prefs"
CALL_TIMEOUT_S = 8.0
MAX_BODY_BYTES = 256 * 1024


class OsmSignInError(Exception):
    """The OpenStreetMap side of a sign-in failed; `reason` is a short code, never a secret."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OsmProfile:
    """What the sign-in keeps of an OpenStreetMap account."""

    uid: int
    display_name: str
    account_created: str | None


def new_state() -> str:
    """An unguessable `state` value for one sign-in attempt."""
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    """A PKCE verifier: 43 to 128 URL-safe characters (RFC 7636)."""
    return secrets.token_urlsafe(64)[:96]


def code_challenge(verifier: str) -> str:
    """The S256 PKCE challenge for a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(*, client_id: str, redirect_url: str, state: str, verifier: str) -> str:
    """Where to send the reviewer to approve the sign-in (scope is always `read_prefs`)."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_url,
            "scope": SCOPE,
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def parse_profile(payload: object) -> OsmProfile:
    """The uid, display name and account creation date out of a `user/details.json` body."""
    user: Any = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict):
        raise OsmSignInError("profile_unreadable")
    uid = user.get("id")
    name = user.get("display_name")
    if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
        raise OsmSignInError("profile_unreadable")
    if not isinstance(name, str) or not name.strip():
        raise OsmSignInError("profile_unreadable")
    created = user.get("account_created")
    return OsmProfile(
        uid=uid,
        display_name=name.strip(),
        account_created=created if isinstance(created, str) else None,
    )


class OsmTokenClient:
    """Exchanges an authorization code for a token and reads the signed-in user's details."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_url: str,
        user_agent: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_url = redirect_url
        self._user_agent = user_agent
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            follow_redirects=False, timeout=httpx.Timeout(CALL_TIMEOUT_S)
        )

    async def aclose(self) -> None:
        """Close the HTTP client if this instance created it."""
        if self._owns_http:
            await self._http.aclose()

    async def profile_for_code(self, code: str, verifier: str) -> OsmProfile:
        """Trade the code for a token, read the profile, and drop the token."""
        token = await self._exchange(code, verifier)
        try:
            return await self._details(token)
        finally:
            del token  # never kept past this call

    async def _exchange(self, code: str, verifier: str) -> str:
        try:
            response = await self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_url,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code_verifier": verifier,
                },
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise OsmSignInError("exchange_unreachable") from exc
        if response.status_code != 200 or len(response.content) > MAX_BODY_BYTES:
            raise OsmSignInError("exchange_refused")
        try:
            token = response.json().get("access_token")
        except (ValueError, AttributeError) as exc:
            raise OsmSignInError("exchange_unreadable") from exc
        if not isinstance(token, str) or not token:
            raise OsmSignInError("exchange_unreadable")
        return token

    async def _details(self, token: str) -> OsmProfile:
        try:
            response = await self._http.get(
                USER_DETAILS_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise OsmSignInError("profile_unreachable") from exc
        if response.status_code != 200 or len(response.content) > MAX_BODY_BYTES:
            raise OsmSignInError("profile_refused")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OsmSignInError("profile_unreadable") from exc
        return parse_profile(payload)

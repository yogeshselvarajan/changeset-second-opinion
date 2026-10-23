"""Invite codes, sessions, cookies and CSRF binding (framework-light core of the auth package).

Nothing here imports `cso.api.deps`, so `deps.get_principal` can build on it without a cycle.

Secrets, and how they are kept:
- An invite code is `cso-<8 hex id>-<32 url-safe secret>`. The database holds an argon2 hash of the
  secret and the public id (needed because a salted hash cannot be searched). The plaintext code
  is printed once at creation and never stored or logged.
- A session cookie carries a random 256-bit token; the database holds only its sha256.
- The CSRF token is random, sent in a readable cookie and echoed in `X-CSRF`; its sha256 is stored
  on the session row, so a forged cookie that never came from this server fails the binding check.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import anyio
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.api.db import get_session_factory
from cso.api.problems import ForbiddenError, InvalidParameterError, UnauthorizedError
from cso.domain.sanitize import sanitize
from cso.persistence.db import session_scope
from cso.persistence.repos._common import utcnow
from cso.persistence.repos.audit_repo import AuditRepo
from cso.persistence.repos.sessions_repo import SessionsRepo
from cso.persistence.tables import InviteCodeRow, SessionRow
from cso.settings import Settings

log = structlog.get_logger("cso.auth")

SESSION_COOKIE = "cso_session"
CSRF_COOKIE = "cso_csrf"
CSRF_HEADER = "X-CSRF"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
VALID_ROLES: tuple[str, ...] = ("viewer", "reviewer", "admin")
DISPLAY_NAME_MAX = 80
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "testserver"})
INVITE_PATTERN = re.compile(r"^cso-([0-9a-f]{8})-([A-Za-z0-9_-]{32})$")
GENERIC_LOGIN_FAILURE = "The invite code is not valid."


class CsrfError(ForbiddenError):
    """The CSRF header is missing or does not match the session (403)."""

    code = "csrf_invalid"


class CrossOriginError(ForbiddenError):
    """The request came from another origin (403)."""

    code = "cross_origin_rejected"


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AuthConfig:
    """Auth behaviour. Env names are listed below.

    Environment overrides read by `from_settings` (all optional): `CSO_AUTH_SESSION_HOURS`,
    `CSO_AUTH_IDLE_MINUTES`, `CSO_COOKIE_SECURE` (auto|true|false), `CSO_TRUST_PROXY`,
    `CSO_LIVE_ANON_READ`.
    """

    mode: Literal["replay", "live"] = "replay"
    session_ttl: timedelta = timedelta(hours=12)
    idle_timeout: timedelta = timedelta(hours=2)
    cookie_secure: bool | None = None  # None: Secure unless the request is plain-http loopback
    trust_proxy: bool = False  # honour X-Forwarded-For / -Proto / -Host from the reverse proxy
    allow_anonymous_read_in_live: bool = False
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65536
    argon2_parallelism: int = 4
    login_attempts: int = 10  # per IP per `login_window`
    login_window: timedelta = timedelta(minutes=15)
    analysis_per_ip_hour: int = 10  # unauthenticated callers (replay mode)
    analysis_per_session_day: int = 60
    mutations_per_ip_minute: int = 120  # generic flood guard on every non-GET under /api

    @classmethod
    def from_settings(cls, settings: Settings) -> AuthConfig:
        """Config for the runtime mode plus optional `CSO_*` environment overrides."""
        env = os.environ
        secure_raw = env.get("CSO_COOKIE_SECURE", "auto").strip().lower()
        secure: bool | None = None if secure_raw == "auto" else _truthy(secure_raw)
        return cls(
            mode=settings.mode,
            session_ttl=timedelta(hours=float(env.get("CSO_AUTH_SESSION_HOURS", "12"))),
            idle_timeout=timedelta(minutes=float(env.get("CSO_AUTH_IDLE_MINUTES", "120"))),
            cookie_secure=secure,
            trust_proxy=_truthy(env.get("CSO_TRUST_PROXY", "false")),
            allow_anonymous_read_in_live=_truthy(env.get("CSO_LIVE_ANON_READ", "false")),
        )


def get_config(request: Request) -> AuthConfig:
    """The app's AuthConfig (set by `install_security`), else the defaults."""
    config = getattr(request.app.state, "auth_config", None)
    return config if isinstance(config, AuthConfig) else AuthConfig()


# --------------------------------------------------------------------------- hashing


def sha256_hex(value: str) -> str:
    """sha256 hex digest of a token (session and CSRF tokens are stored only in this form)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Compare two strings without leaking where they differ."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class InviteHasher:
    """argon2 hashing off the event loop, with a dummy verify so unknown codes cost the same."""

    def __init__(self, config: AuthConfig) -> None:
        self._ph = PasswordHasher(
            time_cost=config.argon2_time_cost,
            memory_cost=config.argon2_memory_cost_kib,
            parallelism=config.argon2_parallelism,
        )
        self._dummy = self._ph.hash(secrets.token_urlsafe(24))

    async def hash(self, secret: str) -> str:
        """argon2 hash of an invite-code secret."""
        return await anyio.to_thread.run_sync(self._ph.hash, secret)

    async def verify(self, stored_hash: str, secret: str) -> bool:
        """True when `secret` matches `stored_hash`; any hash problem counts as a mismatch."""

        def check() -> bool:
            try:
                return bool(self._ph.verify(stored_hash, secret))
            except (VerificationError, InvalidHashError):
                return False

        return await anyio.to_thread.run_sync(check)

    async def verify_dummy(self, secret: str) -> None:
        """Burn the same time as a real verify (for unknown or malformed codes)."""
        await self.verify(self._dummy, secret)


def parse_invite_code(code: str) -> tuple[str, str] | None:
    """Split a code into (public id, secret); None when it is not shaped like one."""
    match = INVITE_PATTERN.fullmatch(code.strip())
    return (match.group(1), match.group(2)) if match else None


def generate_invite_code() -> tuple[str, str, str]:
    """A fresh (code, code_id, secret); the code is shown once and never stored."""
    code_id = secrets.token_hex(4)
    secret = secrets.token_urlsafe(24)
    return f"cso-{code_id}-{secret}", code_id, secret


async def create_invite(
    db: AsyncSession,
    hasher: InviteHasher,
    *,
    role: str,
    label: str = "",
    max_uses: int | None = None,
    ttl: timedelta | None = None,
    created_by: str | None = None,
    now: datetime | None = None,
) -> tuple[str, InviteCodeRow]:
    """Create an invite code and return (plaintext code, stored row). Caller commits."""
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {', '.join(VALID_ROLES)}")
    if max_uses is not None and max_uses < 1:
        raise ValueError("max_uses must be at least 1")
    moment = now or utcnow()
    repo = SessionsRepo(db)
    for _ in range(8):
        code, code_id, secret = generate_invite_code()
        if await repo.get_invite_by_code_id(code_id) is None:
            row = await repo.add_invite_code(
                code_hash=await hasher.hash(secret),
                role=role,
                label=label,
                code_id=code_id,
                created_by=created_by,
                max_uses=max_uses,
                expires_at=moment + ttl if ttl is not None else None,
                now=moment,
            )
            return code, row
    raise RuntimeError("could not find a free invite code id")


# --------------------------------------------------------------------------- login / logout


@dataclass(frozen=True)
class LoginResult:
    """A new session and the two secrets that go into cookies (never stored in plaintext)."""

    session: SessionRow
    token: str
    csrf: str


def clean_display_name(raw: str) -> str:
    """Normalised display name: NFKC, no control or invisible characters, collapsed whitespace."""
    name = sanitize(raw, max_len=DISPLAY_NAME_MAX).text
    if not name:
        raise InvalidParameterError("display_name has no visible characters.")
    return name


def refusal_message(invite: InviteCodeRow, now: datetime) -> str | None:
    """Why a correct code was refused, for the person who holds it: revoked, expired or used up."""
    if invite.revoked_at is not None or invite.disabled:
        return "That invite code has been revoked. Ask an admin for a new one."
    if invite.expires_at is not None and invite.expires_at <= now:
        return "That invite code has expired. Ask an admin for a new one."
    if invite.max_uses is not None and invite.use_count >= invite.max_uses:
        return "That invite code has already been used the most times it allows."
    return None


async def login(
    db: AsyncSession,
    *,
    config: AuthConfig,
    hasher: InviteHasher,
    invite_code: str,
    display_name: str,
    previous_token: str | None,
    request_id: str | None,
    now: datetime | None = None,
) -> LoginResult:
    """Exchange an invite code for a new session; every failure looks identical to the caller.

    Unknown, malformed, wrong, spent, expired and disabled codes all return the same 401 after
    the same amount of hashing work. A failed attempt is audited (without the code) and committed
    before the error is raised, because the request's transaction would otherwise roll back.
    """
    moment = now or utcnow()
    name = clean_display_name(display_name)
    repo = SessionsRepo(db)
    audit = AuditRepo(db)

    parsed = parse_invite_code(invite_code)
    invite = await repo.get_invite_by_code_id(parsed[0]) if parsed else None
    valid = False
    if parsed is not None and invite is not None:
        valid = await hasher.verify(invite.code_hash, parsed[1])
    else:
        await hasher.verify_dummy(parsed[1] if parsed else secrets.token_urlsafe(24))
    specific: str | None = None
    if valid and invite is not None:
        valid = invite.role in VALID_ROLES and await repo.consume_invite(invite.id, now=moment)
        if not valid:
            # Only someone holding the real secret reaches this point, so saying why is no oracle.
            specific = refusal_message(invite, moment)
    if not valid or invite is None:
        await audit.append(
            actor="anonymous",
            action="auth.login_failed",
            payload={"reason": "invite_code_not_accepted"},
            request_id=request_id,
            now=moment,
        )
        await db.commit()
        log.info("auth.login_failed", request_id=request_id)
        raise UnauthorizedError(specific or GENERIC_LOGIN_FAILURE)

    rotated = False
    if previous_token:
        old = await repo.get_by_token_hash(sha256_hex(previous_token))
        if old is not None and not old.revoked:
            await repo.revoke(old.id)
            rotated = True

    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    row = await repo.create_session(
        invite_code_id=invite.id,
        display_name=name,
        role=invite.role,
        expires_at=moment + config.session_ttl,
        token_hash=sha256_hex(token),
        csrf_hash=sha256_hex(csrf),
        now=moment,
    )
    await audit.append(
        actor=name,
        action="auth.login",
        payload={"role": invite.role, "rotated": rotated},
        session_id=row.id,
        request_id=request_id,
        now=moment,
    )
    log.info("auth.login", request_id=request_id, role=invite.role, rotated=rotated)
    return LoginResult(session=row, token=token, csrf=csrf)


async def logout(db: AsyncSession, row: SessionRow, *, request_id: str | None) -> None:
    """Revoke the session and audit it. Caller commits."""
    await SessionsRepo(db).revoke(row.id)
    await AuditRepo(db).append(
        actor=row.display_name,
        action="auth.logout",
        payload={},
        session_id=row.id,
        request_id=request_id,
    )
    log.info("auth.logout", request_id=request_id)


async def resolve_session(
    db: AsyncSession, config: AuthConfig, token: str | None, *, now: datetime | None = None
) -> SessionRow | None:
    """The live session for a cookie token (not revoked, not expired, not idle), else None."""
    if not token:
        return None
    repo = SessionsRepo(db)
    moment = now or utcnow()
    row = await repo.get_active_by_token_hash(
        sha256_hex(token), now=moment, idle_timeout=config.idle_timeout
    )
    if row is not None:
        await repo.touch(row, now=moment)
    return row


def verify_csrf_binding(
    row: SessionRow, header_value: str | None, cookie_value: str | None
) -> None:
    """Raise CsrfError unless the header equals the cookie and matches this session's token."""
    if not header_value or not cookie_value or not row.csrf_hash:
        raise CsrfError("The X-CSRF header is required for this request.")
    if not constant_time_equals(header_value, cookie_value):
        raise CsrfError("The X-CSRF header does not match.")
    if not constant_time_equals(sha256_hex(header_value), row.csrf_hash):
        raise CsrfError("The X-CSRF header does not match this session.")


# --------------------------------------------------------------------------- database access


def session_factory_for(request: Request) -> async_sessionmaker[AsyncSession]:
    """The app's session factory: `app.state.session_factory`, else built on first use.

    The lazy path is `cso.api.db.get_session_factory`, the same one the routers use, so the app
    has one engine however the first request arrives (a login, a read, or a cookie check).
    """
    return get_session_factory(request)


async def get_auth_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request, from the app's session factory."""
    async with session_scope(session_factory_for(request)) as session:
        yield session


def get_hasher(request: Request) -> InviteHasher:
    """The app's InviteHasher (set by `install_security`), created on first use otherwise."""
    hasher = getattr(request.app.state, "auth_hasher", None)
    if not isinstance(hasher, InviteHasher):
        hasher = InviteHasher(get_config(request))
        request.app.state.auth_hasher = hasher
    return hasher


# --------------------------------------------------------------------------- request helpers


def client_ip(request: Request, config: AuthConfig) -> str:
    """The caller's address; behind a trusted proxy the rightmost X-Forwarded-For hop."""
    if config.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hop = forwarded.split(",")[-1].strip()
            if hop:
                return hop
    return request.client.host if request.client else "unknown"


def request_is_secure(request: Request, config: AuthConfig) -> bool:
    """Whether to set the Secure cookie flag: always, except for plain-http loopback requests."""
    if config.cookie_secure is not None:
        return config.cookie_secure
    scheme = request.url.scheme
    if config.trust_proxy:
        scheme = request.headers.get("x-forwarded-proto", scheme).split(",")[0].strip()
    if scheme == "https":
        return True
    return (request.url.hostname or "") not in LOOPBACK_HOSTS


def set_login_cookies(
    response: Response, request: Request, config: AuthConfig, token: str, csrf: str
) -> None:
    """`cso_session` (HttpOnly, Path=/api) and the readable `cso_csrf` (Path=/) cookies."""
    secure = request_is_secure(request, config)
    max_age = int(config.session_ttl.total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        path="/api",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def clear_login_cookies(response: Response, request: Request, config: AuthConfig) -> None:
    """Expire both cookies with the same attributes they were set with."""
    secure = request_is_secure(request, config)
    response.delete_cookie(
        SESSION_COOKIE, path="/api", secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")

"""Readiness checks: database reachable, migrations at head, model server healthy.

`/readyz` reports 200 only when these hold (the model server only matters in live mode). The
Decider probe talks to the server's own `GET /health` with a short timeout and does not go through
the client's single-flight gate, so a long analysis in flight never makes the service look down.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache

import httpx
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.api.schemas import DeciderHealth
from cso.persistence.admin import alembic_config

DeciderProbe = Callable[[], Awaitable[DeciderHealth]]
PROBE_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class DatabaseReadiness:
    """What the database check found; `ok` needs both fields true."""

    reachable: bool
    at_head: bool

    @property
    def ok(self) -> bool:
        return self.reachable and self.at_head


@lru_cache
def head_revision() -> str | None:
    """The newest migration revision shipped with this code."""
    script = ScriptDirectory.from_config(alembic_config("sqlite:///:memory:"))
    return script.get_current_head()


async def check_database(factory: async_sessionmaker[AsyncSession]) -> DatabaseReadiness:
    """`SELECT 1`, then compare the stored revision with the code's head."""
    try:
        async with factory() as session:
            await session.execute(sa.text("SELECT 1"))
            try:
                row = (
                    await session.execute(sa.text("SELECT version_num FROM alembic_version"))
                ).first()
            except Exception:  # no version table: the schema was never migrated
                return DatabaseReadiness(reachable=True, at_head=False)
    except Exception:
        return DatabaseReadiness(reachable=False, at_head=False)
    return DatabaseReadiness(reachable=True, at_head=row is not None and row[0] == head_revision())


def make_decider_probe(
    base_url: str, *, client: httpx.AsyncClient | None = None, timeout: float = PROBE_TIMEOUT_S
) -> DeciderProbe:
    """A probe for `GET {base_url}/health` that returns `DeciderHealth` and never raises."""
    url = base_url.rstrip("/") + "/health"

    async def probe() -> DeciderHealth:
        owned = client is None
        http = client or httpx.AsyncClient(timeout=timeout)
        try:
            response = await http.get(url, timeout=timeout)
            if response.status_code != 200:
                return DeciderHealth(ok=False)
            body = response.json()
            if not isinstance(body, dict) or body.get("status") != "ok":
                return DeciderHealth(ok=False)
            return DeciderHealth(
                ok=True,
                model=_text(body.get("model")),
                checkpoint=_text(body.get("checkpoint")),
                device=_text(body.get("device")),
            )
        except (httpx.HTTPError, ValueError):
            return DeciderHealth(ok=False)
        finally:
            if owned:
                await http.aclose()

    return probe


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None

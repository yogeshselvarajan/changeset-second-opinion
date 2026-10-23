"""Readiness. `/healthz` (process alive) stays in `main.py`; this adds `/readyz`.

The database check is real: the database must answer and its migrations must be at the code's head
(`observability.readiness.check_database`). The model-server check reads a probe that the lifespan
sets on `app.state.decider_probe` (an async callable returning `DeciderHealth`) when
`CSO_DECIDER_URL` is configured; without one the model server reports `ok: false`, which only
matters in live mode. The probe result is cached for 10 seconds, and a 503 names what failed.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request

from cso.api.db import SessionFactoryDep, SettingsDep
from cso.api.problems import ServiceUnavailableError, problem_responses
from cso.api.routing import make_router
from cso.api.schemas import DeciderHealth, ReadyzResponse
from cso.observability.readiness import DatabaseReadiness, check_database

router = make_router(tags=["health"])

CACHE_SECONDS = 10.0
DeciderProbe = Callable[[], Awaitable[DeciderHealth]]


async def _decider_health(request: Request) -> DeciderHealth:
    state = request.app.state
    cached: tuple[float, DeciderHealth] | None = getattr(state, "decider_health_cache", None)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    probe: DeciderProbe | None = getattr(state, "decider_probe", None)
    if probe is None:
        health = DeciderHealth(ok=False)
    else:
        try:
            health = await probe()
        except Exception:
            health = DeciderHealth(ok=False)
    state.decider_health_cache = (time.monotonic(), health)
    return health


@router.get(
    "/readyz",
    response_model=ReadyzResponse,
    summary="Readiness of the database and the model server",
    responses=problem_responses(503),
)
async def readyz(
    request: Request, factory: SessionFactoryDep, settings: SettingsDep
) -> ReadyzResponse:
    """200 when ready; live mode also needs the model server (replay runs without it)."""
    database: DatabaseReadiness = await check_database(factory)
    decider = await _decider_health(request)
    if not database.ok or (settings.mode == "live" and not decider.ok):
        raise ServiceUnavailableError(
            "The service is not ready.",
            db=database.ok,
            db_reachable=database.reachable,
            migrations_at_head=database.at_head,
            decider=decider.model_dump(mode="json"),
        )
    return ReadyzResponse(db=database.ok, decider=decider)

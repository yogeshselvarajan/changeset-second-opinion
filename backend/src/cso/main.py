from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from cso import __version__
from cso.api.app import mount_api
from cso.api.auth_core import AuthConfig
from cso.api.db import dispose_session_factory
from cso.jobs import EmbeddedWorker
from cso.observability import (
    RequestContextMiddleware,
    configure_from_settings,
    get_logger,
    make_decider_probe,
)
from cso.observability.endpoints import router as metrics_router
from cso.observability.readiness import PROBE_TIMEOUT_S
from cso.settings import get_settings

log = get_logger("cso.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fails startup on invalid settings (live mode needs a real User-Agent).
    settings = get_settings()
    configure_from_settings(settings)
    app.state.auth_config = AuthConfig.from_settings(settings)
    probe_client: httpx.AsyncClient | None = None
    if settings.decider_url and getattr(app.state, "decider_probe", None) is None:
        probe_client = httpx.AsyncClient(timeout=PROBE_TIMEOUT_S)
        app.state.decider_probe = make_decider_probe(settings.decider_url, client=probe_client)
    worker = EmbeddedWorker(settings) if settings.jobs_worker_enabled else None
    if worker is not None:
        await worker.start()  # skipped with a warning until `cso db upgrade` has run
    log.info("app.started", mode=settings.mode, version=__version__, worker=worker is not None)
    try:
        yield
    finally:
        if worker is not None:
            await worker.stop()
        if probe_client is not None:
            await probe_client.aclose()
        await dispose_session_factory(app)
        log.info("app.stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Changeset Second Opinion", version=__version__, lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    mount_api(app)
    app.include_router(metrics_router)  # loopback-only, outside the public contract
    # Added last, so it is the outermost middleware: request ids reach every inner problem.
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()

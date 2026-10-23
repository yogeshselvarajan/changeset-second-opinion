"""Database access for the routers: one session factory per application.

The factory is created on first use from `CSO_DATABASE_URL` and kept on `app.state`; tests set
`app.state.session_factory` (or override `get_session_factory`) before the first request. Each
endpoint runs inside `session_scope`, so its writes commit before the response is built and a
raised problem rolls everything back.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cso.persistence.db import make_engine, make_sessionmaker
from cso.settings import Settings, get_settings

SessionFactory = async_sessionmaker[AsyncSession]


def get_session_factory(request: Request) -> SessionFactory:
    """The application's session factory, built from the settings on first use."""
    state = request.app.state
    factory: SessionFactory | None = getattr(state, "session_factory", None)
    if factory is None:
        engine = make_engine(get_settings().database_url)
        factory = make_sessionmaker(engine)
        state.engine = engine
        state.session_factory = factory
    return factory


async def dispose_session_factory(app: FastAPI) -> None:
    """Close the engine that `get_session_factory` created (call from a shutdown hook)."""
    engine: AsyncEngine | None = getattr(app.state, "engine", None)
    if engine is not None:
        await engine.dispose()
        app.state.engine = None
        app.state.session_factory = None


def app_settings() -> Settings:
    """The process settings (a dependency so tests can override it)."""
    return get_settings()


SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]
SettingsDep = Annotated[Settings, Depends(app_settings)]

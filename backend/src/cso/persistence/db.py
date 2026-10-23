"""Engine and session factory (SQLAlchemy 2.0 async; SQLite WAL by default, Postgres supported)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cso.persistence.guard import install_engine_guard, install_session_guard

SQLITE_BUSY_TIMEOUT_MS = 5000


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def make_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Build the async engine; SQLite connections get WAL, busy_timeout and foreign keys."""
    install_session_guard()
    parsed = make_url(url)
    engine = create_async_engine(url, echo=echo)
    if parsed.get_backend_name() == "sqlite":
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    install_engine_guard(engine)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory; objects stay readable after commit (expire_on_commit=False)."""
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """One transaction: commit on success, roll back on any error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

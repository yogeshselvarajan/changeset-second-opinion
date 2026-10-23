"""Alembic environment (async). SQLite runs in batch mode; the URL defaults to CSO_DATABASE_URL."""

from __future__ import annotations

import asyncio
import warnings

import sqlalchemy as sa
from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from cso.persistence.tables import Base
from cso.settings import get_settings

config = context.config
target_metadata = Base.metadata

# SQLite cannot reflect DESC expression indexes, so autogenerate cannot compare them. They are
# written by hand in the migration and verified by tests/integration/test_migrations.py.
warnings.filterwarnings("ignore", message="autogenerate skipping metadata-specified expression")


def _expression_index_names() -> frozenset[str]:
    """Indexes with DESC/expression parts: reflection loses them, so they cannot be compared."""
    return frozenset(
        index.name
        for table in target_metadata.tables.values()
        for index in table.indexes
        if index.name and any(not isinstance(e, sa.Column) for e in index.expressions)
    )


_UNCOMPARABLE_INDEXES = _expression_index_names()


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    return not (type_ == "index" and name in _UNCOMPARABLE_INDEXES)


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _configure(connection: Connection | None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        literal_binds=connection is None,
        render_as_batch=True,
        compare_type=True,
        include_object=_include_object,
        dialect_opts={"paramstyle": "named"},
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a database connection."""
    _configure(None, _url())
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    engine = create_async_engine(_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

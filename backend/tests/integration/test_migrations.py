"""Migrations: SQLite upgrade/check/downgrade, Postgres DDL rendering, optional live Postgres.

The live Postgres test needs `testcontainers` and a Docker daemon; without them it is skipped and
that step counts as NOT RUN (the offline DDL test below still proves the SQL renders for Postgres).
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from cso.persistence.admin import alembic_config, upgrade_database
from cso.persistence.tables import Base

BACKEND = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = set(Base.metadata.tables) | {"alembic_version"}


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


def _names(db: Path, kind: str) -> set[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'", (kind,)
        ).fetchall()
    return {r[0] for r in rows}


def test_upgrade_head_creates_every_table_and_index(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    upgrade_database(_sqlite_url(db))
    assert _names(db, "table") == EXPECTED_TABLES
    metadata_indexes = {
        index.name for table in Base.metadata.tables.values() for index in table.indexes
    }
    assert metadata_indexes <= _names(db, "index")


def test_desc_indexes_really_are_descending(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    upgrade_database(_sqlite_url(db))
    with sqlite3.connect(db) as conn:
        sql = {
            name: ddl
            for name, ddl in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        }
    for name in (
        "ix_review_cases_queue",
        "ix_review_cases_status",
        "ix_analysis_runs_case",
        "ix_drafts_run",
        "ix_human_outcomes_case",
        "ix_jobs_claim",
    ):
        assert "DESC" in sql[name].upper(), name


def test_models_and_migration_do_not_drift(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    upgrade_database(_sqlite_url(db))
    command.check(alembic_config(_sqlite_url(db)))  # raises when autogenerate finds a difference


def test_alembic_ini_works_from_the_backend_directory(tmp_path: Path) -> None:
    db = tmp_path / "ini.db"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _sqlite_url(db))
    command.upgrade(cfg, "head")
    assert _names(db, "table") == EXPECTED_TABLES


def test_downgrade_to_base_and_back(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    cfg = alembic_config(_sqlite_url(db))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert _names(db, "table") <= {"alembic_version"}
    command.upgrade(cfg, "head")
    assert _names(db, "table") == EXPECTED_TABLES


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    upgrade_database(_sqlite_url(db))
    upgrade_database(_sqlite_url(db))
    assert _names(db, "table") == EXPECTED_TABLES


def test_postgres_ddl_renders_offline() -> None:
    cfg = alembic_config("postgresql+psycopg://user:pw@localhost/cso")
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    ddl = cfg.output_buffer.getvalue()
    assert "CREATE TABLE review_cases" in ddl
    assert "JSONB" in ddl
    assert "is_active BOOLEAN DEFAULT false NOT NULL" in ddl  # not DEFAULT 0, invalid on Postgres
    assert (
        "CREATE INDEX ix_review_cases_queue ON review_cases (lane_rank, created_at DESC, id)" in ddl
    )
    assert (
        "CREATE INDEX ix_jobs_claim ON jobs (status, run_after, priority DESC, created_at)" in ddl
    )
    assert "ON DELETE SET NULL" in ddl
    assert "UUID" in ddl and "TIMESTAMP WITH TIME ZONE" in ddl


def test_postgres_migrations_against_a_real_server() -> None:
    postgres = pytest.importorskip("testcontainers.postgres", reason="testcontainers not installed")
    try:
        container = postgres.PostgresContainer("postgres:17", driver="psycopg")
        container.start()
    except Exception as exc:  # Docker daemon unavailable, image pull blocked, ...
        pytest.skip(f"Postgres container could not start: {exc}")
    try:
        url = container.get_connection_url()
        upgrade_database(url)
        command.check(alembic_config(url))
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
        finally:
            engine.dispose()
        assert tables == EXPECTED_TABLES
    finally:
        container.stop()

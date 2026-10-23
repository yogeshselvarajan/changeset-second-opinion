"""`cso auth create-invite`: prints the code once and stores only a hash."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from auth_support import make_config

from cso.api.auth_core import InviteHasher, login, parse_invite_code
from cso.cli import main
from cso.persistence.db import make_engine, make_sessionmaker, session_scope
from cso.settings import get_settings


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cli.db"
    monkeypatch.setenv("CSO_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def test_create_invite_prints_the_code_once_and_stores_only_a_hash(
    database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "auth",
                "create-invite",
                "--role",
                "admin",
                "--max-uses",
                "2",
                "--ttl-hours",
                "1",
                "--label",
                "for-anna",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    code = captured.out.strip()
    assert parse_invite_code(code) is not None and "\n" not in code
    assert "role=admin" in captured.err and "max_uses=2" in captured.err
    assert code not in captured.err  # the code goes to stdout only

    secret = code.split("-", 2)[2]
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT code_hash, code_id, role, label, max_uses, use_count, expires_at "
            "FROM invite_codes"
        ).fetchone()
        dump = "".join(
            str(r)
            for table in ("invite_codes", "sessions", "audit_events")
            for r in conn.execute(f"SELECT * FROM {table}")  # noqa: S608
        )
    assert row[0].startswith("$argon2id$") and row[2] == "admin" and row[3] == "for-anna"
    assert row[4] == 2 and row[5] == 0 and row[6] is not None
    assert code not in dump and secret not in dump


@pytest.fixture
def cli_code(database: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """A reviewer code made by the real CLI (synchronous: `main` starts its own event loop)."""
    assert main(["auth", "create-invite", "--role", "reviewer"]) == 0
    return capsys.readouterr().out.strip()


async def test_a_cli_created_code_can_log_in(database: Path, cli_code: str) -> None:
    code = cli_code
    config = make_config()
    engine = make_engine(f"sqlite+aiosqlite:///{database}")
    try:
        async with session_scope(make_sessionmaker(engine)) as db:
            result = await login(
                db,
                config=config,
                hasher=InviteHasher(config),
                invite_code=code,
                display_name="Anna",
                previous_token=None,
                request_id="r1",
            )
        assert result.session.role == "reviewer" and result.session.display_name == "Anna"
    finally:
        await engine.dispose()


def test_create_invite_rejects_an_unknown_role(database: Path) -> None:
    with pytest.raises(SystemExit):
        main(["auth", "create-invite", "--role", "superuser"])


def test_create_invite_rejects_a_zero_use_limit(
    database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["auth", "create-invite", "--max-uses", "0"]) == 1
    assert "max_uses" in capsys.readouterr().err

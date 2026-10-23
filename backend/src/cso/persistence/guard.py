"""Immutability guard: UPDATE/DELETE on snapshots, runs, drafts, outcomes and audit raise.

Three layers, because one is easy to bypass by accident:
1. `before_flush`: a dirty or deleted ORM instance of an immutable model.
2. `do_orm_execute`: an UPDATE/DELETE statement (ORM or Core) aimed at an immutable table.
3. `before_cursor_execute` on the engine: raw SQL text that starts with UPDATE/DELETE on one.

On Postgres the deployment should also revoke UPDATE/DELETE from the application role.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Delete, Update, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import ORMExecuteState, Session, UOWTransaction

from cso.persistence.errors import ImmutableRowError
from cso.persistence.tables import IMMUTABLE_MODELS, IMMUTABLE_TABLES

_TABLES_PATTERN = "|".join(sorted(IMMUTABLE_TABLES))
_RAW_WRITE = re.compile(
    rf"^\s*(?:UPDATE|DELETE\s+FROM)\s+[\"`\[]?(?:{_TABLES_PATTERN})[\"`\]]?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

_session_guard_installed = False


def _refuse(table: str, verb: str) -> ImmutableRowError:
    return ImmutableRowError(
        f"{verb} on immutable table '{table}' is not allowed; record a new row instead"
    )


def _before_flush(session: Session, _ctx: UOWTransaction, _instances: Any) -> None:
    for obj in session.dirty:
        if isinstance(obj, IMMUTABLE_MODELS) and session.is_modified(obj):
            raise _refuse(type(obj).__tablename__, "UPDATE")
    for obj in session.deleted:
        if isinstance(obj, IMMUTABLE_MODELS):
            raise _refuse(type(obj).__tablename__, "DELETE")


def _do_orm_execute(state: ORMExecuteState) -> None:
    statement = state.statement
    if isinstance(statement, Update | Delete):
        name = getattr(statement.table, "name", None)
        if name in IMMUTABLE_TABLES:
            raise _refuse(str(name), "UPDATE" if isinstance(statement, Update) else "DELETE")


def install_session_guard() -> None:
    """Attach the ORM-level guards to every Session (idempotent)."""
    global _session_guard_installed
    if _session_guard_installed:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "do_orm_execute", _do_orm_execute)
    _session_guard_installed = True


def _before_cursor_execute(
    _conn: Any, _cursor: Any, statement: str, _params: Any, _ctx: Any, _many: bool
) -> None:
    match = _RAW_WRITE.match(statement)
    if match:
        verb = "DELETE" if match.group(0).lstrip().upper().startswith("DELETE") else "UPDATE"
        raise _refuse(match.group(0).split()[-1].strip('"`[]'), verb)


def install_engine_guard(engine: AsyncEngine | Engine) -> None:
    """Reject raw UPDATE/DELETE text against immutable tables on this engine."""
    sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)

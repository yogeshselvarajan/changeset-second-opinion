"""Errors raised by the persistence layer."""

from __future__ import annotations

from typing import Any


class PersistenceError(Exception):
    """Base class for persistence failures."""


class ImmutableRowError(PersistenceError):
    """An UPDATE or DELETE targeted a table whose rows are immutable (corrections are new rows)."""


class VersionConflictError(PersistenceError):
    """An optimistic lock failed: the case outcome version moved since the caller read it."""

    def __init__(self, *, expected: int, current: int, current_outcome_id: Any = None) -> None:
        super().__init__(f"outcome version conflict: expected {expected}, current {current}")
        self.expected = expected
        self.current = current
        self.current_outcome_id = current_outcome_id


class NotFoundError(PersistenceError):
    """A referenced row does not exist."""

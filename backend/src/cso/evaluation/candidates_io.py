"""Candidate records: anonymised metadata about changesets considered for labelling.

Committed candidate files carry no display names, emails or evidence text: a mapper is only a
salted hash, and the MapRoulette status is kept under an explicitly weak name.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cso.domain.enums import ChangeAction
from cso.domain.models import EvidenceSnapshot

SOURCE_MAPROULETTE = "maproulette"
SOURCE_RECENT_NEW = "recent_new_accounts"

# MapRoulette task status codes (weak signal only, never a label).
MR_STATUS_NAMES = {
    0: "created",
    1: "fixed",
    2: "false_positive",
    3: "skipped",
    4: "deleted",
    5: "already_fixed",
    6: "too_hard",
    7: "answered",
    8: "validated",
    9: "disabled",
}


def mapper_hash(uid: int | None, changeset_id: int) -> str:
    """Salted hash of the author's uid (changeset id when the uid is hidden): 16 hex chars."""
    key = f"uid:{uid}" if uid is not None else f"cs:{changeset_id}"
    return hashlib.sha256(f"cso-eval-mapper-v1:{key}".encode()).hexdigest()[:16]


def age_bucket(days: int | None) -> str:
    """Coarse account-age bucket (never the exact age)."""
    if days is None:
        return "unknown"
    if days < 7:
        return "lt7d"
    if days < 30:
        return "lt30d"
    if days < 365:
        return "lt1y"
    return "ge1y"


@dataclass(frozen=True)
class Candidate:
    """One candidate changeset, anonymised."""

    changeset_id: int
    mapper_hash: str
    source: str
    flags: tuple[str, ...]
    coverage_score: float
    elements: int
    deletes: int
    account_age: str
    weak_mr_status: str | None = None  # WEAK signal; never ground truth
    created_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def stratum(self) -> str:
        """Split-balancing stratum derived from parsed evidence and the weak source signal."""
        lowered = {f.lower() for f in self.flags}
        if "mass deletion" in lowered or self.deletes > 0:
            return "deletions"
        if "new mapper" in lowered or self.account_age in ("lt7d", "lt30d"):
            return "new_mapper"
        if self.weak_mr_status in ("fixed", "validated"):
            return "mr_fixed"
        if self.weak_mr_status in ("false_positive", "already_fixed"):
            return "mr_not_issue"
        return "other"

    def to_json(self) -> dict[str, Any]:
        return {
            "changeset_id": self.changeset_id,
            "mapper_hash": self.mapper_hash,
            "source": self.source,
            "flags": list(self.flags),
            "coverage_score": round(self.coverage_score, 4),
            "elements": self.elements,
            "deletes": self.deletes,
            "account_age": self.account_age,
            "weak_mr_status": self.weak_mr_status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Candidate:
        return cls(
            changeset_id=int(raw["changeset_id"]),
            mapper_hash=raw["mapper_hash"],
            source=raw["source"],
            flags=tuple(raw.get("flags", [])),
            coverage_score=float(raw.get("coverage_score", 0.0)),
            elements=int(raw.get("elements", 0)),
            deletes=int(raw.get("deletes", 0)),
            account_age=raw.get("account_age", "unknown"),
            weak_mr_status=raw.get("weak_mr_status"),
            created_at=raw.get("created_at"),
        )


def candidate_from_snapshot(
    snapshot: EvidenceSnapshot, *, source: str, mr_status: int | None = None
) -> Candidate:
    """Reduce a collected snapshot to an anonymised `Candidate`."""
    cs = snapshot.changeset
    created: datetime = cs.created_at
    return Candidate(
        changeset_id=cs.id,
        mapper_hash=mapper_hash(cs.uid, cs.id),
        source=source,
        flags=tuple(sorted(snapshot.flags)),
        coverage_score=snapshot.coverage.score,
        elements=snapshot.coverage.elements_in_changeset,
        deletes=snapshot.element_counts.get(ChangeAction.DELETE, 0),
        account_age=age_bucket(snapshot.user.account_age_days if snapshot.user else None),
        weak_mr_status=MR_STATUS_NAMES.get(mr_status, f"status_{mr_status}")
        if mr_status is not None
        else None,
        created_at=created.date().isoformat(),
    )

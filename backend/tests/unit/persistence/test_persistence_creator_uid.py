"""`ChangedObject.created_by_uid` is additive: snapshots stored before it existed still load."""

from __future__ import annotations

from persistence_support import store_case
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.models import EvidenceSnapshot
from cso.persistence.db import session_scope
from cso.persistence.repos import SnapshotsRepo


def _without_creator(snapshot: EvidenceSnapshot) -> dict[str, object]:
    raw = snapshot.model_dump(mode="json")
    for element in raw["elements"]:
        element.pop("created_by_uid")
    return raw


def test_old_snapshot_json_without_the_field_loads_with_none(snapshot_02: EvidenceSnapshot) -> None:
    raw = _without_creator(snapshot_02)
    assert all("created_by_uid" not in e for e in raw["elements"])  # type: ignore[attr-defined]
    loaded = EvidenceSnapshot.model_validate(raw)
    assert [e.created_by_uid for e in loaded.elements] == [None] * len(loaded.elements)
    assert loaded.evidence_version == snapshot_02.evidence_version


async def test_creator_uid_survives_a_round_trip(
    factory: async_sessionmaker[AsyncSession], snapshot_02: EvidenceSnapshot
) -> None:
    created = [e for e in snapshot_02.elements if e.created_by_uid is not None]
    assert created  # fixture 02 creates an element, attributed to the changeset's own account
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_02, with_run=False)
    async with factory() as s:
        loaded = await SnapshotsRepo(s).get(stored.snapshot_id)
    assert loaded is not None
    assert [e.created_by_uid for e in loaded.elements] == [
        e.created_by_uid for e in snapshot_02.elements
    ]

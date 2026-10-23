"""Parsed fact: deleted elements created by the changeset's own account within 30 days."""

from __future__ import annotations

from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.models import EvidenceSnapshot
from cso.domain.policy import (
    OWN_RECENT_MAX_AGE_DAYS,
    deleted_own_recent_additions,
    own_recent_deletions,
    parsed_facts,
)

CONFIG = CommunityConfig.load()
CASES = Path(__file__).parents[3] / "fixtures" / "cases"


async def snapshot_of(name: str) -> EvidenceSnapshot:
    client = ReplayClient(CASES / name)
    return await collect(client, client.case.changeset.id)


def with_deletions(snapshot: EvidenceSnapshot, count: int, **update: object) -> EvidenceSnapshot:
    elements = [
        e.model_copy(update=update) if i < count else e for i, e in enumerate(snapshot.elements)
    ]
    return snapshot.model_copy(update={"elements": elements})


async def test_no_deleted_elements_is_false_not_unknown() -> None:
    snapshot = await snapshot_of("02-good-faith-mistake")
    assert own_recent_deletions(snapshot) == (0, 0)
    assert deleted_own_recent_additions(snapshot) is False


async def test_deletions_by_another_creator_do_not_count() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    own_recent, determinable = own_recent_deletions(snapshot)
    assert (own_recent, determinable) == (0, 40)  # creator is a different account in the fixture
    assert deleted_own_recent_additions(snapshot) is None  # 86 of 126 deletions have no details


@pytest.mark.parametrize("age", [0, 1, OWN_RECENT_MAX_AGE_DAYS])
async def test_own_recent_deletions_are_true_up_to_30_days(age: int) -> None:
    snapshot = await snapshot_of("04-large-deletion")
    uid = snapshot.changeset.uid
    changed = with_deletions(snapshot, 2, created_by_uid=uid, age_days=age)
    assert own_recent_deletions(changed)[0] == 2
    assert deleted_own_recent_additions(changed) is True
    assert parsed_facts(changed, CONFIG).deleted_own_recent_additions is True


async def test_older_own_additions_do_not_count() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    changed = with_deletions(
        snapshot, 3, created_by_uid=snapshot.changeset.uid, age_days=OWN_RECENT_MAX_AGE_DAYS + 1
    )
    assert own_recent_deletions(changed)[0] == 0


async def test_unknown_creator_or_age_is_not_a_no() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    unknown = with_deletions(snapshot, 40, created_by_uid=None)
    assert own_recent_deletions(unknown) == (0, 0)
    assert deleted_own_recent_additions(unknown) is None
    no_age = with_deletions(snapshot, 40, age_days=None)
    assert own_recent_deletions(no_age) == (0, 0)


async def test_unknown_changeset_account_cannot_be_matched() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    anonymous = snapshot.model_copy(
        update={"changeset": snapshot.changeset.model_copy(update={"uid": None})}
    )
    assert own_recent_deletions(anonymous) == (0, 0)

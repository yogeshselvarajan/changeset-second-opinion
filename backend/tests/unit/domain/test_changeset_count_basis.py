"""Changeset count at edit time (changeset tag) versus the account's current total."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.evidence import render
from cso.domain.fixtures import (
    apply_edit_time_count,
    changeset_from_api,
    parse_edit_time_count,
    user_from_api,
)
from cso.domain.models import ChangesetMeta, EvidenceSnapshot, UserFacts
from cso.domain.policy import new_account_first_edits

CONFIG = CommunityConfig.load()
CASES = Path(__file__).parents[3] / "fixtures" / "cases"


async def snapshot_of(name: str) -> EvidenceSnapshot:
    client = ReplayClient(CASES / name)
    return await collect(client, client.case.changeset.id)


def raw_changeset(tags: dict[str, str]) -> dict[str, object]:
    return {
        "changeset": {
            "id": 900000000999,
            "uid": 1,
            "user": "mapper_x",
            "created_at": "2026-03-01T10:00:00Z",
            "tags": tags,
        }
    }


# ----------------------------------------------------------------------- tag parsing


@pytest.mark.parametrize(
    ("value", "expected"),
    [("5", 5), ("0", 0), ("1242", 1242), ("007", 7)],
)
def test_valid_tag_values_are_parsed(value: str, expected: int) -> None:
    assert parse_edit_time_count({"changesets_count": value}) == expected


@pytest.mark.parametrize(
    "value",
    ["-3", "abc", "", " 5", "5 ", "1.5", "1e3", "٣", "9999999999", "+4", None, 5],
)
def test_garbage_negative_or_non_string_values_are_ignored(value: object) -> None:
    tags: dict[str, object] = {} if value is None else {"changesets_count": value}
    assert parse_edit_time_count(tags) is None  # type: ignore[arg-type]


def test_missing_tag_is_none() -> None:
    assert parse_edit_time_count({"comment": "x"}) is None


def test_changeset_meta_carries_the_tag() -> None:
    assert changeset_from_api(raw_changeset({"changesets_count": "5"})).changesets_count == 5
    assert changeset_from_api(raw_changeset({"changesets_count": "x"})).changesets_count is None
    assert changeset_from_api(raw_changeset({})).changesets_count is None


# ------------------------------------------------------------------ model back-compat


def test_old_json_without_the_new_fields_still_loads() -> None:
    user = UserFacts.model_validate({"uid": 1, "account_age_days": 30, "changesets_count": 12})
    assert user.changesets_count == 12 and user.changesets_count_basis is None
    meta = ChangesetMeta.model_validate({"id": 1, "created_at": "2026-03-01T10:00:00Z"})
    assert meta.changesets_count is None


async def test_old_snapshot_json_round_trips_without_the_new_fields() -> None:
    snapshot = await snapshot_of("08-adversarial-text")
    data = snapshot.model_dump(mode="json")
    data["changeset"].pop("changesets_count")
    data["user"].pop("changesets_count_basis")
    loaded = EvidenceSnapshot.model_validate(data)
    assert loaded.user is not None and loaded.user.changesets_count_basis is None


# ------------------------------------------------------------- merge: edit time vs current


def current_user(count: int | None = 29, age: int | None = 100) -> UserFacts:
    return UserFacts(uid=1, account_age_days=age, changesets_count=count)


def meta_with(count: int | None) -> ChangesetMeta:
    return ChangesetMeta(id=1, created_at=datetime(2026, 3, 1, tzinfo=UTC), changesets_count=count)


def test_tag_replaces_the_current_total_and_is_labelled_edit_time() -> None:
    merged = apply_edit_time_count(current_user(29), meta_with(5))
    assert merged is not None
    assert (merged.changesets_count, merged.changesets_count_basis) == (5, "edit_time")


def test_without_the_tag_the_current_total_is_kept_and_labelled_current() -> None:
    merged = apply_edit_time_count(current_user(29), meta_with(None))
    assert merged is not None
    assert (merged.changesets_count, merged.changesets_count_basis) == (29, "current")


def test_no_user_stays_none_and_no_count_is_not_invented() -> None:
    assert apply_edit_time_count(None, meta_with(5)) is None
    merged = apply_edit_time_count(current_user(None), meta_with(None))
    assert merged is not None and merged.changesets_count is None
    assert merged.changesets_count_basis is None


def test_user_from_api_labels_its_count_as_current() -> None:
    raw = {"user": {"id": 1, "display_name": "m", "changesets": {"count": 7}}}
    facts = user_from_api(raw, as_of=datetime(2026, 3, 1, tzinfo=UTC))
    assert (facts.changesets_count, facts.changesets_count_basis) == (7, "current")


# -------------------------------------------------------------------- collector (replay)


async def test_collector_uses_the_edit_time_tag_when_present() -> None:
    snapshot = await snapshot_of("01-legitimate")
    assert snapshot.changeset.changesets_count == 1150
    assert snapshot.user is not None
    assert (snapshot.user.changesets_count, snapshot.user.changesets_count_basis) == (
        1150,
        "edit_time",
    )  # the account's current total in user.json is 1200


async def test_collector_keeps_the_current_total_without_the_tag() -> None:
    snapshot = await snapshot_of("08-adversarial-text")
    assert snapshot.changeset.changesets_count is None
    assert snapshot.user is not None
    assert (snapshot.user.changesets_count, snapshot.user.changesets_count_basis) == (4, "current")


def test_evidence_version_ignores_the_count() -> None:
    import sys
    from datetime import UTC, datetime

    version = sys.modules["cso.adapters.osm.collect"]._evidence_version
    fetched = datetime(2026, 3, 2, tzinfo=UTC)
    base = meta_with(None).model_copy(update={"closed_at": fetched})
    tagged = base.model_copy(update={"changesets_count": 5})
    assert version(base, (), [], fetched) == version(tagged, (), [], fetched)


# ----------------------------------------------------------------------- USER line


async def test_user_line_says_edit_time_for_both_profiles() -> None:
    snapshot = await snapshot_of("02-good-faith-mistake")
    for profile in ("full", "compact"):
        text = render(snapshot, CONFIG, profile=profile).text  # type: ignore[arg-type]
        assert "changesets at the time of this edit: 2" in text
        assert "changesets in total now" not in text


async def test_user_line_says_current_total_for_both_profiles() -> None:
    snapshot = await snapshot_of("08-adversarial-text")
    for profile in ("full", "compact"):
        text = render(snapshot, CONFIG, profile=profile).text  # type: ignore[arg-type]
        assert "changesets in total now: 4 (count at edit time not published)" in text
        assert "at the time of this edit" not in text


async def test_user_line_with_unknown_count() -> None:
    snapshot = await snapshot_of("08-adversarial-text")
    assert snapshot.user is not None
    bare = snapshot.model_copy(
        update={
            "user": snapshot.user.model_copy(
                update={"changesets_count": None, "changesets_count_basis": None}
            )
        }
    )
    for profile in ("full", "compact"):
        assert "changesets: unknown" in render(bare, CONFIG, profile=profile).text  # type: ignore[arg-type]


async def test_budgets_still_hold_on_every_fixture() -> None:
    for case in sorted(p for p in CASES.iterdir() if p.is_dir()):
        snapshot = await snapshot_of(case.name)
        assert render(snapshot, CONFIG, profile="compact").estimated_tokens <= 1200
        assert render(snapshot, CONFIG, profile="full").estimated_tokens <= 3000


# ------------------------------------------------------------ parsed fact truth table


async def table_snapshot(
    *,
    age: int | None,
    user_count: int | None,
    basis: str | None,
    tag: int | None = None,
    has_user: bool = True,
) -> EvidenceSnapshot:
    base = await snapshot_of("08-adversarial-text")
    user = (
        UserFacts(
            uid=1,
            account_age_days=age,
            changesets_count=user_count,
            changesets_count_basis=basis,  # type: ignore[arg-type]
        )
        if has_user
        else None
    )
    meta = base.changeset.model_copy(update={"changesets_count": tag})
    return base.model_copy(update={"user": user, "changeset": meta})


@pytest.mark.parametrize(
    ("age", "count", "basis", "expected"),
    [
        # age under 7 days is always True
        (3, 500, "edit_time", True),
        (3, 500, "current", True),
        (0, None, None, True),
        # edit-time counts decide when the age is known
        (100, 5, "edit_time", True),
        (100, 9, "edit_time", True),
        (100, 10, "edit_time", False),
        (7, 10, "edit_time", False),
        (6, 10, "edit_time", True),
        # a current total can only prove "few"; it can never prove "many"
        (100, 9, "current", True),
        (100, 0, "current", True),
        (100, 10, "current", None),
        (100, 1200, "current", None),
        (100, 10, None, None),  # old snapshot without a basis counts as current
        (100, 4, None, True),
        # unknowns
        (None, 5, "edit_time", True),
        (None, 50, "edit_time", None),  # age unknown: a young account cannot be ruled out
        (None, 50, "current", None),
        (None, 5, "current", True),
        (100, None, None, None),
        (None, None, None, None),
    ],
)
async def test_new_account_truth_table(
    age: int | None, count: int | None, basis: str | None, expected: bool | None
) -> None:
    snapshot = await table_snapshot(age=age, user_count=count, basis=basis)
    assert new_account_first_edits(snapshot) is expected


async def test_tag_on_the_changeset_decides_when_the_user_profile_is_missing() -> None:
    few = await table_snapshot(age=None, user_count=None, basis=None, tag=4, has_user=False)
    many = await table_snapshot(age=None, user_count=None, basis=None, tag=40, has_user=False)
    nothing = await table_snapshot(age=None, user_count=None, basis=None, has_user=False)
    assert new_account_first_edits(few) is True
    assert new_account_first_edits(many) is None
    assert new_account_first_edits(nothing) is None


async def test_tag_beats_a_larger_current_total_in_the_fact() -> None:
    snapshot = await table_snapshot(age=100, user_count=29, basis="current", tag=5)
    assert new_account_first_edits(snapshot) is True  # 5 at the time, 29 now


# -------------------------------------------- review F-M5: a lying tag cannot lower caution


@pytest.mark.parametrize("tag", [4, 29])
def test_a_tag_up_to_the_current_total_is_used(tag: int) -> None:
    merged = apply_edit_time_count(current_user(29), meta_with(tag))
    assert merged is not None
    assert (merged.changesets_count, merged.changesets_count_basis) == (tag, "edit_time")


@pytest.mark.parametrize("tag", [30, 5000, 10**8])
def test_a_tag_above_the_current_total_is_ignored_and_the_basis_stays_current(tag: int) -> None:
    merged = apply_edit_time_count(current_user(29), meta_with(tag))
    assert merged is not None
    assert (merged.changesets_count, merged.changesets_count_basis) == (29, "current")


def test_a_lying_large_tag_on_a_three_changeset_account_still_reads_as_a_new_account() -> None:
    user = apply_edit_time_count(current_user(3, age=400), meta_with(5000))
    snapshot = EvidenceSnapshot.model_construct(
        changeset=meta_with(5000), user=user, discussion=[], objects=[]
    )
    assert new_account_first_edits(snapshot) is True
    assert user is not None and "5000" not in str(user.model_dump())


def test_policy_ignores_an_implausible_tag_left_on_a_snapshot() -> None:
    """Even a snapshot that kept the raw tag (older code) cannot be talked into `False`."""
    snapshot = EvidenceSnapshot.model_construct(
        changeset=meta_with(5000), user=current_user(50, age=400), discussion=[], objects=[]
    )
    assert new_account_first_edits(snapshot) is None  # not False: 50 now does not prove 10+ then

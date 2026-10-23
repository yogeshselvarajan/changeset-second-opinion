from __future__ import annotations

from pathlib import Path

import pytest

from cso.adapters.osm import (
    ElementCapExceededError,
    NotFoundError,
    OsmSource,
    OsmTimeoutError,
    Redacted403,
    ReplayClient,
    parse_osm_change,
)
from cso.domain.enums import OsmType
from cso.domain.fixtures import Marker

CASES_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "cases"
CASE_DIRS = sorted(p for p in CASES_DIR.iterdir() if p.is_dir())


def case(prefix: str) -> Path:
    return next(p for p in CASE_DIRS if p.name.startswith(prefix))


def test_all_eight_fixtures_are_present() -> None:
    assert [p.name[:2] for p in CASE_DIRS] == [f"{i:02d}" for i in range(1, 9)]


def test_replay_client_satisfies_the_protocol() -> None:
    assert isinstance(ReplayClient(case("01")), OsmSource)


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.name)
async def test_replay_serves_changeset_and_osc_consistent_with_expected(case_dir: Path) -> None:
    client = ReplayClient(case_dir)
    expected = client.case.expected
    meta = await client.get_changeset(expected.changeset_id)
    assert meta["changeset"]["id"] == expected.changeset_id
    osc = await client.get_osc(expected.changeset_id)
    try:
        parsed = parse_osm_change(osc)
    except ElementCapExceededError:
        assert expected.coverage.snapshot_truncated
        return
    if not expected.coverage.snapshot_truncated:
        assert parsed.raw_element_count == expected.coverage.elements_in_changeset
    assert client.calls == 2


async def test_replay_unknown_changeset_is_not_found() -> None:
    client = ReplayClient(case("01"))
    with pytest.raises(NotFoundError):
        await client.get_changeset(1)
    with pytest.raises(NotFoundError):
        await client.get_osc(1)


async def test_replay_returns_prior_versions_and_copies() -> None:
    client = ReplayClient(case("02"))
    key = next(iter(client.case.prev))
    first = await client.get_element_version(*key)
    assert (first["type"], first["id"], first["version"]) == (key[0].value, key[1], key[2])
    first["tags"]["name"] = "mutated"
    again = await client.get_element_version(*key)
    assert again["tags"]["name"] != "mutated"  # callers cannot corrupt the fixture


async def test_replay_missing_version_is_not_found() -> None:
    client = ReplayClient(case("02"))
    with pytest.raises(NotFoundError):
        await client.get_element_version(OsmType.WAY, 1, 1)


async def test_replay_403_marker_raises_redacted_and_history_is_empty() -> None:
    client = ReplayClient(case("06"))
    keys = list(client.case.prev_markers)
    assert keys
    assert all(client.case.prev_markers[k] is Marker.FORBIDDEN for k in keys)
    osm_type, osm_id, version = keys[0]
    with pytest.raises(Redacted403):
        await client.get_element_version(osm_type, osm_id, version)
    # like the live API, redacted versions are simply absent from history; replay adds no fallback
    assert await client.get_element_history(osm_type, osm_id) == []


async def test_replay_timeout_markers_for_prev_and_user() -> None:
    client = ReplayClient(case("07"))
    timeouts = [k for k, m in client.case.prev_markers.items() if m is Marker.TIMEOUT]
    assert timeouts
    with pytest.raises(OsmTimeoutError):
        await client.get_element_version(*timeouts[0])
    assert client.case.user_marker is Marker.TIMEOUT
    with pytest.raises(OsmTimeoutError):
        await client.get_user(client.case.changeset.uid or 1)


async def test_replay_user_matches_uid_and_unknown_uid_is_not_found() -> None:
    client = ReplayClient(case("01"))
    uid = client.case.changeset.uid
    assert uid is not None
    assert (await client.get_user(uid))["user"]["id"] == uid
    with pytest.raises(NotFoundError):
        await client.get_user(uid + 1)


async def test_replay_history_lists_readable_versions_ascending() -> None:
    client = ReplayClient(case("02"))
    osm_type, osm_id, version = next(iter(client.case.prev))
    history = await client.get_element_history(osm_type, osm_id)
    assert [e["version"] for e in history] == [version]
    with pytest.raises(NotFoundError):
        await client.get_element_history(OsmType.WAY, 1)


async def test_replay_multi_fetch_is_all_or_nothing() -> None:
    client = ReplayClient(case("02"))
    osm_type, osm_id, version = next(iter(client.case.prev))
    got = await client.get_elements(osm_type, [osm_id])
    assert got[osm_id]["version"] == version
    with pytest.raises(NotFoundError):
        await client.get_elements(osm_type, [osm_id, 1])
    with pytest.raises(ValueError, match="at most 200"):
        await client.get_elements(osm_type, list(range(1, 202)))

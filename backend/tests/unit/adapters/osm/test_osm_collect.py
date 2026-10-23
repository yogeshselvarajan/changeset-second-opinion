from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import respx

from cso.adapters.osm import (
    BandwidthLimitError,
    CollectBudget,
    NotFoundError,
    OsmClient,
    OsmTimeoutError,
    PriorVersionCache,
    Redacted403,
    ReplayClient,
    TooLargeError,
    UpstreamError,
    collect,
)
from cso.domain.enums import (
    ChangeAction,
    CoverageGapReason,
    EvidenceSource,
    FetchStatus,
    OsmType,
    TagChange,
)

CASES = sorted((Path(__file__).parents[4] / "fixtures" / "cases").iterdir())
CS = 910_000_000_001
FIXED_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return FIXED_NOW


# ------------------------------------------------------------------ replay over all fixtures


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_replay_reproduces_expected_coverage_and_flags(case_dir: Path) -> None:
    client = ReplayClient(case_dir)
    snap = await collect(client, client.case.changeset.id)
    expected = client.case.expected

    assert snap.coverage == expected.coverage
    assert snap.flags == expected.flags
    assert snap.source is EvidenceSource.REPLAY
    assert client.calls <= 50
    assert len(snap.elements) == expected.coverage.elements_detailed
    assert snap.evidence_version.startswith("sha256:")
    assert {g.osm_id for g in snap.coverage.history_gaps} == {
        g.osm_id for g in expected.coverage.history_gaps
    }


async def test_replay_good_faith_mistake_has_tag_diff_against_prior_version() -> None:
    client = ReplayClient(next(p for p in CASES if p.name.startswith("02-")))
    snap = await collect(client, client.case.changeset.id)

    way = next(e for e in snap.elements if e.osm_type is OsmType.WAY)
    assert (way.version_before, way.version_after) == (3, 4)
    assert way.tags_before == {"highway": "residential", "name": "Elm Street"}
    diff = next(d for d in snap.tag_diffs if d.key == "name")
    assert (diff.before, diff.after, diff.change) == (
        "Elm Street",
        "Corner Bakery",
        TagChange.CHANGED,
    )
    created = next(e for e in snap.elements if e.action is ChangeAction.CREATE)
    assert created.tags_before is None and created.version_before is None
    assert {d.change for d in snap.tag_diffs if d.osm_id == created.osm_id} == {TagChange.ADDED}


async def test_replay_large_deletion_recovers_prior_tags_and_age() -> None:
    client = ReplayClient(next(p for p in CASES if p.name.startswith("04-")))
    snap = await collect(client, client.case.changeset.id)

    school = snap.elements[0]
    assert school.action is ChangeAction.DELETE and school.tags_after is None
    assert school.tags_before is not None and school.tags_before.get("amenity") == "school"
    assert school.age_days is not None and school.age_days > 365 * 5
    assert all(d.change is TagChange.REMOVED for d in snap.tag_diffs)


async def test_replay_adversarial_text_is_kept_raw_for_the_renderer_to_sanitize() -> None:
    client = ReplayClient(next(p for p in CASES if p.name.startswith("08-")))
    snap = await collect(client, client.case.changeset.id)

    assert any("IGNORE PREVIOUS INSTRUCTIONS" in d.text for d in snap.discussion)
    assert "suspect_word" in snap.flags


# ------------------------------------------------------------------ synthetic source


def changeset_raw(
    *,
    uid: int | None = 7,
    open_: bool = False,
    comments: list[dict[str, Any]] | None = None,
    changes: int = 1,
    bbox: tuple[float, float, float, float] = (13.0, 52.0, 13.1, 52.1),
    comments_count: int | None = None,
    with_comments_key: bool = True,
) -> dict[str, Any]:
    cs: dict[str, Any] = {
        "id": CS,
        "created_at": "2026-03-01T10:00:00Z",
        "open": open_,
        "comments_count": len(comments or []) if comments_count is None else comments_count,
        "changes_count": changes,
        "min_lon": bbox[0],
        "min_lat": bbox[1],
        "max_lon": bbox[2],
        "max_lat": bbox[3],
        "tags": {"comment": "synthetic", "created_by": "JOSM/1.5", "source": "survey"},
    }
    if not open_:
        cs["closed_at"] = "2026-03-01T10:30:00Z"
    if uid is not None:
        cs["uid"] = uid
        cs["user"] = "mapper_T"
    if with_comments_key:
        cs["comments"] = comments or []
    return {"version": "0.6", "copyright": "OSM contributors", "changeset": cs}


def user_raw(count: int = 1000) -> dict[str, Any]:
    return {
        "user": {
            "id": 7,
            "display_name": "mapper_T",
            "account_created": "2020-01-01T00:00:00Z",
            "changesets": {"count": count},
            "blocks": {"received": {"count": 0, "active": 0}},
        }
    }


type Spec = tuple[str, str, int, int, dict[str, str]]  # action, type, id, version, tags


def osc_bytes(items: Sequence[Spec], extra: dict[tuple[str, int], str] | None = None) -> bytes:
    blocks: list[str] = []
    for action, osm_type, osm_id, version, tags in items:
        attrs = (extra or {}).get((osm_type, osm_id), "")
        body = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        blocks.append(
            f'<{action}><{osm_type} id="{osm_id}" version="{version}" '
            f'changeset="{CS}" timestamp="2026-03-01T10:05:00Z" {attrs}>{body}'
            f"</{osm_type}></{action}>"
        )
    return f'<osmChange version="0.6">{"".join(blocks)}</osmChange>'.encode()


def prior(
    osm_type: str, osm_id: int, version: int, tags: dict[str, str] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "type": osm_type,
        "id": osm_id,
        "version": version,
        "timestamp": "2024-01-01T00:00:00Z",
        "visible": True,
        "tags": tags or {"highway": "residential"},
        **extra,
    }


class FakeSource:
    """In-memory OsmSource with per-key failures and optional latency."""

    def __init__(
        self,
        osc: bytes | Exception,
        *,
        changeset: dict[str, Any] | Exception | None = None,
        user: dict[str, Any] | Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.calls = 0
        self._osc = osc
        self._changeset = changeset if changeset is not None else changeset_raw()
        self._user = user if user is not None else user_raw()
        self.versions: dict[tuple[OsmType, int, int], dict[str, Any] | Exception] = {}
        self.histories: dict[tuple[OsmType, int], list[dict[str, Any]] | Exception] = {}
        self.history_calls = 0
        self._delay = delay_s

    async def _tick(self) -> None:
        self.calls += 1
        if self._delay:
            await anyio.sleep(self._delay)

    async def get_changeset(self, changeset_id: int) -> dict[str, Any]:
        await self._tick()
        if isinstance(self._changeset, Exception):
            raise self._changeset
        return self._changeset

    async def get_osc(self, changeset_id: int) -> bytes:
        await self._tick()
        if isinstance(self._osc, Exception):
            raise self._osc
        return self._osc

    async def get_element_version(
        self, osm_type: OsmType, osm_id: int, version: int
    ) -> dict[str, Any]:
        await self._tick()
        found = self.versions.get((osm_type, osm_id, version))
        if isinstance(found, Exception):
            raise found
        if found is None:
            raise NotFoundError(f"{osm_type}/{osm_id}/{version}")
        return found

    async def get_element_history(self, osm_type: OsmType, osm_id: int) -> list[dict[str, Any]]:
        await self._tick()
        self.history_calls += 1
        found = self.histories.get((osm_type, osm_id), [])
        if isinstance(found, Exception):
            raise found
        return found

    async def get_elements(
        self, osm_type: OsmType, osm_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        await self._tick()
        raise AssertionError("collect must not multi-fetch")

    async def get_user(self, uid: int) -> dict[str, Any]:
        await self._tick()
        if isinstance(self._user, Exception):
            raise self._user
        return self._user


def one_modify(source_tags: dict[str, str] | None = None, version: int = 2) -> bytes:
    return osc_bytes([("modify", "way", 11, version, source_tags or {"highway": "path"})])


# ------------------------------------------------------------------ budget and ranking


async def test_300_element_changeset_stays_within_50_calls_and_records_skips() -> None:
    items: list[Spec] = [("modify", "way", 1000 + i, 2, {"highway": "path"}) for i in range(300)]
    source = FakeSource(osc_bytes(items), changeset=changeset_raw(changes=300))
    for i in range(300):
        source.versions[(OsmType.WAY, 1000 + i, 1)] = prior("way", 1000 + i, 1)

    snap = await collect(source, CS, clock=_clock)

    assert source.calls <= 50
    assert snap.coverage.elements_in_changeset == 300
    assert snap.coverage.elements_detailed == 40
    assert snap.coverage.elements_skipped_budget == 260
    assert [e.osm_id for e in snap.elements] == list(range(1000, 1040))  # document-order ties
    assert snap.coverage.score == pytest.approx(40 / 300, abs=1e-6)


async def test_total_call_budget_is_a_hard_cap_and_leftovers_become_budget_gaps() -> None:
    items: list[Spec] = [("modify", "way", 2000 + i, 2, {"highway": "path"}) for i in range(10)]
    source = FakeSource(osc_bytes(items))
    for i in range(10):
        source.versions[(OsmType.WAY, 2000 + i, 1)] = prior("way", 2000 + i, 1)

    snap = await collect(source, CS, CollectBudget(max_total_calls=8), clock=_clock)

    assert source.calls <= 8
    reasons = [g.reason for g in snap.coverage.history_gaps]
    assert reasons and set(reasons) == {CoverageGapReason.BUDGET}
    assert snap.coverage.elements_detailed == 10  # ranked inside the budget, but not reconstructed


async def test_ranking_is_deletions_then_priority_modifies_then_other_then_creates() -> None:
    items: list[Spec] = [
        ("create", "node", 1, 1, {"shop": "bakery"}),
        ("modify", "way", 2, 2, {"surface": "asphalt"}),
        ("modify", "way", 3, 2, {"name": "Main Street"}),
        ("delete", "node", 4, 3, {}),
        ("modify", "way", 5, 2, {"addr:street": "Elm Street"}),
    ]
    source = FakeSource(osc_bytes(items))
    for key in [
        (OsmType.WAY, 2, 1),
        (OsmType.WAY, 3, 1),
        (OsmType.NODE, 4, 2),
        (OsmType.WAY, 5, 1),
    ]:
        source.versions[key] = prior(key[0].value, key[1], key[2])

    snap = await collect(source, CS, CollectBudget(max_elements_detailed=4), clock=_clock)

    assert [e.osm_id for e in snap.elements] == [4, 3, 5, 2]  # create (rank 3) is the one skipped
    assert snap.coverage.elements_skipped_budget == 1


# ------------------------------------------------------------------ gaps and failures


async def test_403_falls_back_to_highest_visible_earlier_version_from_history() -> None:
    source = FakeSource(one_modify(version=5))
    source.versions[(OsmType.WAY, 11, 4)] = Redacted403("redacted")
    # the API omits redacted versions from history, so v4 is simply absent
    source.histories[(OsmType.WAY, 11)] = [
        prior("way", 11, 1, {"highway": "track"}),
        prior("way", 11, 2, {"highway": "path"}),
        prior("way", 11, 3, {}, visible=False),
        prior("way", 11, 5, {"highway": "path"}),  # at or after this changeset's v5: ignored
    ]

    snap = await collect(source, CS, clock=_clock)

    assert snap.coverage.history_gaps == []
    assert snap.elements[0].version_before == 2 and snap.elements[0].tags_before == {
        "highway": "path"
    }


@pytest.mark.parametrize(
    ("failure", "history", "reason"),
    [
        (Redacted403("x"), [], CoverageGapReason.REDACTED),
        (Redacted403("x"), NotFoundError("x"), CoverageGapReason.REDACTED),
        (Redacted403("x"), OsmTimeoutError("x"), CoverageGapReason.TIMEOUT),
        (NotFoundError("x"), [], CoverageGapReason.NOT_FOUND),
        (OsmTimeoutError("x"), [], CoverageGapReason.TIMEOUT),
        (UpstreamError("boom", status=500), [], CoverageGapReason.TIMEOUT),
    ],
)
async def test_each_prior_failure_becomes_a_typed_gap_and_the_run_completes(
    failure: Exception, history: list[dict[str, Any]] | Exception, reason: CoverageGapReason
) -> None:
    source = FakeSource(one_modify())
    source.versions[(OsmType.WAY, 11, 1)] = failure
    source.histories[(OsmType.WAY, 11)] = history

    snap = await collect(source, CS, clock=_clock)

    assert [(g.osm_id, g.reason) for g in snap.coverage.history_gaps] == [(11, reason)]
    assert snap.elements[0].tags_before is None and snap.tag_diffs == []
    assert snap.coverage.score == 0.0  # the only detailed element has a gap


async def test_http_509_stops_the_stage_and_no_further_calls_are_made() -> None:
    items: list[Spec] = [("modify", "way", 3000 + i, 2, {"highway": "path"}) for i in range(10)]
    source = FakeSource(osc_bytes(items))
    source.versions[(OsmType.WAY, 3000, 1)] = BandwidthLimitError("509", status=509)

    snap = await collect(source, CS, clock=_clock)

    assert source.calls <= 3 + 10  # meta, osc, user, then at most one attempt per element
    assert {g.reason for g in snap.coverage.history_gaps} == {CoverageGapReason.BUDGET}
    assert len(snap.coverage.history_gaps) == 10


async def test_history_calls_are_capped_at_five() -> None:
    items: list[Spec] = [("modify", "way", 4000 + i, 2, {"highway": "path"}) for i in range(8)]
    source = FakeSource(osc_bytes(items))
    for i in range(8):
        source.versions[(OsmType.WAY, 4000 + i, 1)] = Redacted403("redacted")

    snap = await collect(source, CS, clock=_clock)

    assert source.history_calls == 5
    assert len(snap.coverage.history_gaps) == 8  # all redacted, beyond the cap without a call


async def test_user_failure_degrades_profile_and_applies_the_score_penalty() -> None:
    ok = await collect(_with_prior(FakeSource(one_modify())), CS, clock=_clock)
    failed = await collect(
        _with_prior(FakeSource(one_modify(), user=OsmTimeoutError("t"))), CS, clock=_clock
    )

    assert ok.coverage.user_profile is FetchStatus.FETCHED and ok.user is not None
    assert failed.coverage.user_profile is FetchStatus.FAILED and failed.user is None
    assert failed.coverage.score == pytest.approx(ok.coverage.score * 0.9)


async def test_missing_author_skips_the_user_fetch() -> None:
    source = _with_prior(FakeSource(one_modify(), changeset=changeset_raw(uid=None)))
    snap = await collect(source, CS, clock=_clock)

    assert snap.coverage.user_profile is FetchStatus.SKIPPED and snap.user is None
    assert source.calls == 3  # changeset, osmChange, one prior; no user call


def _with_prior(source: FakeSource) -> FakeSource:
    source.versions[(OsmType.WAY, 11, 1)] = prior("way", 11, 1)
    return source


@pytest.mark.parametrize("error", [TooLargeError("big", limit=1)])
async def test_oversized_osmchange_gives_a_truncated_snapshot_not_a_failure(
    error: Exception,
) -> None:
    source = FakeSource(error, changeset=changeset_raw(changes=7000))
    snap = await collect(source, CS, clock=_clock)

    assert snap.coverage.snapshot_truncated is True
    assert snap.coverage.elements_in_changeset == 7000
    assert snap.coverage.elements_detailed == 0 and snap.elements == []
    assert snap.coverage.score == 0.0


async def test_element_cap_exceeded_is_truncated() -> None:
    items: list[Spec] = [("create", "node", 10 + i, 1, {}) for i in range(5001)]
    snap = await collect(FakeSource(osc_bytes(items), changeset=changeset_raw(changes=5001)), CS)

    assert snap.coverage.snapshot_truncated is True and snap.elements == []


async def test_missing_changeset_is_a_fatal_error() -> None:
    with pytest.raises(NotFoundError):
        await collect(FakeSource(one_modify(), changeset=NotFoundError("gone")), CS)


async def test_stage_clock_turns_unfinished_elements_into_timeout_gaps() -> None:
    source = FakeSource(one_modify(), delay_s=0.0)
    source.versions[(OsmType.WAY, 11, 1)] = prior("way", 11, 1)
    slow = _SlowPrior(source)

    snap = await collect(slow, CS, CollectBudget(stage_timeout_s=0.05), clock=_clock)

    assert [(g.osm_id, g.reason) for g in snap.coverage.history_gaps] == [
        (11, CoverageGapReason.TIMEOUT)
    ]


class _SlowPrior:
    """Delegates to a FakeSource but never answers prior-version calls in time."""

    def __init__(self, inner: FakeSource) -> None:
        self._inner = inner

    @property
    def calls(self) -> int:
        return self._inner.calls

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def get_element_version(self, *args: Any) -> dict[str, Any]:
        await anyio.sleep(30)
        raise AssertionError("cancelled by the stage clock")


# ------------------------------------------------------------------ derived facts


async def test_age_comes_from_v1_directly_or_from_one_history_call() -> None:
    source = FakeSource(
        osc_bytes(
            [
                ("modify", "way", 21, 2, {"highway": "path"}),
                ("modify", "way", 22, 4, {"highway": "path"}),
            ]
        )
    )
    source.versions[(OsmType.WAY, 21, 1)] = prior("way", 21, 1, timestamp="2020-03-01T10:00:00Z")
    source.versions[(OsmType.WAY, 22, 3)] = prior("way", 22, 3)
    source.histories[(OsmType.WAY, 22)] = [
        prior("way", 22, 1, timestamp="2023-03-01T10:00:00Z"),
        prior("way", 22, 3),
    ]

    snap = await collect(source, CS, clock=_clock)

    by_id = {e.osm_id: e for e in snap.elements}
    assert (
        by_id[21].age_days
        == (datetime(2026, 3, 1, 10, 0, tzinfo=UTC) - datetime(2020, 3, 1, 10, 0, tzinfo=UTC)).days
    )
    assert by_id[22].age_days == 1096
    assert source.history_calls == 1


async def test_geometry_change_for_moved_node_and_changed_way() -> None:
    source = FakeSource(
        osc_bytes(
            [("modify", "node", 31, 2, {}), ("modify", "way", 32, 2, {"highway": "path"})],
            extra={("node", 31): 'lat="52.001" lon="13.0"'},
        )
    )
    source.versions[(OsmType.NODE, 31, 1)] = prior("node", 31, 1, {}, lat=52.0, lon=13.0)
    source.versions[(OsmType.WAY, 32, 1)] = prior("way", 32, 1, nodes=[1, 2, 3])

    snap = await collect(source, CS, clock=_clock)

    by_id = {e.osm_id: e for e in snap.elements}
    moved = by_id[31].geometry_change
    assert moved is not None and moved.node_moved_m == pytest.approx(111.2, abs=0.5)
    way_geometry = by_id[32].geometry_change
    assert (
        way_geometry is not None and way_geometry.way_node_delta == -3
    )  # osmChange way has no nds


async def test_element_counts_flags_and_open_changeset_provisional() -> None:
    source = FakeSource(
        osc_bytes([("create", "node", 41, 1, {"a": "b"}), ("delete", "node", 42, 2, {})]),
        changeset=changeset_raw(open_=True, bbox=(179.5, -10.0, -179.5, 10.0)),
    )
    source.versions[(OsmType.NODE, 42, 1)] = prior("node", 42, 1, {"a": "b"})

    snap = await collect(source, CS, clock=_clock)

    assert snap.provisional is True
    assert snap.changeset.bbox_wraps is True  # antimeridian
    assert snap.element_counts == {ChangeAction.CREATE: 1, ChangeAction.DELETE: 1}


async def test_discussion_hides_invisible_comments_and_flags_a_missing_discussion() -> None:
    comments = [
        {"id": 1, "visible": True, "date": "2026-03-01T11:00:00Z", "user": "a", "text": "hello"},
        {"id": 2, "visible": False, "date": "2026-03-01T11:05:00Z", "user": "b", "text": "hidden"},
    ]
    shown = await collect(
        _with_prior(FakeSource(one_modify(), changeset=changeset_raw(comments=comments))), CS
    )
    missing = await collect(
        _with_prior(
            FakeSource(
                one_modify(),
                changeset=changeset_raw(comments_count=3, with_comments_key=False),
            )
        ),
        CS,
    )

    assert [d.id for d in shown.discussion] == [1]
    assert shown.coverage.discussion is FetchStatus.FETCHED
    assert missing.coverage.discussion is FetchStatus.FAILED


async def test_flag_failures_do_not_fail_the_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    from cso.adapters.osm import FlagsUnavailableError

    def boom(*_a: object, **_k: object) -> list[str]:
        raise FlagsUnavailableError("no word list")

    # `cso.adapters.osm.collect` the attribute is the function; patch the module itself
    monkeypatch.setattr(sys.modules["cso.adapters.osm.collect"], "compute_flags", boom)
    snap = await collect(_with_prior(FakeSource(one_modify())), CS)

    assert snap.flags == []


# ------------------------------------------------------------------ evidence_version and cache


async def test_evidence_version_is_deterministic_and_tracks_the_inputs() -> None:
    def make(**kw: Any) -> FakeSource:
        return _with_prior(FakeSource(one_modify(version=kw.pop("version", 2)), **kw))

    base = await collect(make(), CS, clock=_clock)
    again = await collect(make(), CS, clock=lambda: datetime(2030, 1, 1, tzinfo=UTC))
    newer_version = await collect(_newer(), CS, clock=_clock)
    commented = await collect(
        make(
            changeset=changeset_raw(
                comments=[
                    {
                        "id": 9,
                        "visible": True,
                        "date": "2026-03-02T00:00:00Z",
                        "user": "a",
                        "text": "x",
                    }
                ]
            )
        ),
        CS,
        clock=_clock,
    )

    assert base.evidence_version == again.evidence_version  # closed: fetched_at is ignored
    assert (
        len({base.evidence_version, newer_version.evidence_version, commented.evidence_version})
        == 3
    )


def _newer() -> FakeSource:
    source = FakeSource(one_modify(version=3))
    source.versions[(OsmType.WAY, 11, 2)] = prior("way", 11, 2)
    return source


async def test_open_changeset_version_changes_with_the_fetched_at_bucket() -> None:
    def make() -> FakeSource:
        return _with_prior(FakeSource(one_modify(), changeset=changeset_raw(open_=True)))

    t0 = datetime(2026, 5, 1, 12, 0, 10, tzinfo=UTC)
    same_bucket = await collect(make(), CS, clock=lambda: t0.replace(second=50))
    first = await collect(make(), CS, clock=lambda: t0)
    later = await collect(make(), CS, clock=lambda: t0.replace(minute=30))

    assert first.evidence_version == same_bucket.evidence_version
    assert first.evidence_version != later.evidence_version


async def test_prior_version_cache_avoids_repeat_fetches() -> None:
    cache = PriorVersionCache()
    first_source = _with_prior(FakeSource(one_modify()))
    await collect(first_source, CS, cache=cache, clock=_clock)
    second_source = FakeSource(one_modify())  # no prior registered: only the cache can serve v-1

    snap = await collect(second_source, CS, cache=cache, clock=_clock)

    assert snap.coverage.history_gaps == []
    assert snap.elements[0].tags_before == {"highway": "residential"}
    assert second_source.calls == 3  # changeset, osmChange, user


# ------------------------------------------------------------------ through the live client


@respx.mock
async def test_collect_through_osm_client_with_mocked_http() -> None:
    base = "https://api.openstreetmap.org/api/0.6"
    ua = "ChangesetSecondOpinion/0.1 (+https://example.test; test@example.test)"
    osc = osc_bytes(
        [
            ("modify", "way", 51, 3, {"highway": "path", "name": "New"}),
            ("delete", "node", 52, 2, {}),
        ]
    )
    changeset_route = respx.get(f"{base}/changeset/{CS}.json").mock(
        return_value=httpx.Response(200, json=changeset_raw(changes=2))
    )
    respx.get(f"{base}/changeset/{CS}/download").mock(return_value=httpx.Response(200, content=osc))
    respx.get(f"{base}/user/7.json").mock(return_value=httpx.Response(200, json=user_raw(count=10)))
    respx.get(f"{base}/way/51/2.json").mock(
        return_value=httpx.Response(
            200, json={"elements": [prior("way", 51, 2, {"highway": "path", "name": "Old"})]}
        )
    )
    respx.get(f"{base}/way/51/history.json").mock(
        return_value=httpx.Response(
            200, json={"elements": [prior("way", 51, 1), prior("way", 51, 2)]}
        )
    )
    respx.get(f"{base}/node/52/1.json").mock(return_value=httpx.Response(403))
    respx.get(f"{base}/node/52/history.json").mock(
        return_value=httpx.Response(
            200, json={"elements": [prior("node", 52, 1, {"amenity": "cafe"})]}
        )
    )
    client = OsmClient(user_agent=ua)
    try:
        snap = await collect(client, CS, clock=_clock)
    finally:
        await client.aclose()

    assert snap.source is EvidenceSource.OSM_API
    assert snap.coverage.history_gaps == []
    assert snap.coverage.elements_detailed == 2
    # changeset, osmChange, user, two priors, node history fallback, way history (age)
    assert client.calls == 7
    deleted = next(e for e in snap.elements if e.osm_id == 52)
    assert deleted.tags_before == {"amenity": "cafe"} and deleted.tags_after is None
    changed = next(d for d in snap.tag_diffs if d.osm_id == 51)
    assert (changed.key, changed.before, changed.after) == ("name", "Old", "New")
    assert "New mapper" in snap.flags  # user fetched with 10 changesets
    assert changeset_route.calls.last.request.headers["user-agent"] == ua
    assert changeset_route.calls.last.request.method == "GET"


async def test_creator_uid_comes_from_version_one_data_without_extra_calls() -> None:
    """A creation inside the changeset is attributed to the changeset's account; a deletion whose
    v-1 is version 1 takes the uid of that version; undeterminable creators stay None."""
    case = next(p for p in CASES if p.name.startswith("04-"))
    client = ReplayClient(case)
    snapshot = await collect(client, client.case.changeset.id)
    deleted = [e for e in snapshot.elements if e.action is ChangeAction.DELETE]
    assert deleted and all(e.created_by_uid == 900000009 for e in deleted)  # v1 prior carries uid

    created = ReplayClient(next(p for p in CASES if p.name.startswith("02-")))
    snap02 = await collect(created, created.case.changeset.id)
    creations = [e for e in snap02.elements if e.action is ChangeAction.CREATE]
    assert creations and all(e.created_by_uid == snap02.changeset.uid for e in creations)

    unknown = ReplayClient(
        next(p for p in CASES if p.name.startswith("06-"))
    )  # every prior version is redacted
    snap06 = await collect(unknown, unknown.case.changeset.id)
    assert all(e.created_by_uid is None for e in snap06.elements)

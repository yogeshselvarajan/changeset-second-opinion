"""Evidence reconstruction: changeset -> EvidenceSnapshot.

Works identically over any `OsmSource` (live `OsmClient` or `ReplayClient`). The coverage record is
always produced, including on partial failure; every element inside the detailed budget either has
its prior version reconstructed or appears in `coverage.history_gaps` with a reason.

Decisions worth knowing:
- Elements are ranked deletions first, then modifies touching name/addr:*/highway/building/amenity,
  then other modifies, then creates; ties keep osmChange document order (stable sort).
- `elements_detailed` counts every ranked element inside `max_elements_detailed`, creates included
  (they need no prior version); `elements_skipped_budget` is the rest. The score denominator is
  every grouped element in the changeset, as in the fixtures.
- Gap reasons: 403 with no readable earlier version -> redacted; 404 -> not_found; timeout or any
  other provider failure -> timeout; our own call budget, a 509 stop or exhausted stage clock ->
  budget (509/budget) or timeout (stage clock).
- Node-coordinate multi-fetch from §3 is intentionally not performed: `GeometryChange` is fully
  computable from the v-1 version and the osmChange (`node_moved_m`, `way_node_delta`), and no
  field consumes fetched coordinates.
- `created_by_uid` comes from version 1 data the age lookup already fetched (no extra calls); an
  element created inside this changeset is attributed to the changeset's own uid.
- Prior versions are not cached across calls unless the caller passes a `PriorVersionCache`.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import anyio
import structlog

from cso.adapters.osm.errors import (
    BandwidthLimitError,
    NotFoundError,
    OsmError,
    OsmTimeoutError,
    Redacted403,
    TooLargeError,
)
from cso.adapters.osm.flags import FlagsUnavailableError, compute_flags
from cso.adapters.osm.parse import GroupedElement, ParsedOsmChange, parse_osm_change
from cso.adapters.osm.protocol import OsmSource
from cso.adapters.osm.replay import ReplayClient
from cso.domain.enums import (
    ChangeAction,
    CoverageGapReason,
    EvidenceSource,
    FetchStatus,
    OsmType,
    TagChange,
)
from cso.domain.fixtures import (
    apply_edit_time_count,
    changeset_from_api,
    discussion_from_api,
    user_from_api,
)
from cso.domain.models import (
    ChangedObject,
    ChangesetMeta,
    Coverage,
    EvidenceSnapshot,
    GeometryChange,
    HistoryGap,
    TagDiff,
    UserFacts,
)

log = structlog.get_logger(__name__)

PRIORITY_KEYS = frozenset({"name", "highway", "building", "amenity"})
PRIORITY_PREFIX = "addr:"
OPEN_CHANGESET_BUCKET_S = 300
EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True, slots=True)
class CollectBudget:
    """Limits for one collection run (defaults are the §3 budget)."""

    max_elements_detailed: int = 40
    max_history_calls: int = 5
    max_total_calls: int = 50
    stage_timeout_s: float = 20.0


class PriorVersionCache:
    """Process-lifetime LRU of prior versions by (type, id, version); versions are immutable."""

    def __init__(self, max_entries: int = 2048) -> None:
        self._max = max_entries
        self._data: OrderedDict[tuple[OsmType, int, int], dict[str, Any]] = OrderedDict()

    def get(self, key: tuple[OsmType, int, int]) -> dict[str, Any] | None:
        """Return a cached element dict and mark it recently used."""
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    def put(self, key: tuple[OsmType, int, int], value: dict[str, Any]) -> None:
        """Store an element dict, evicting the least recently used entry when full."""
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)


class _Gate:
    """Counts calls we start so the run can never exceed the budget, whatever the source does."""

    def __init__(self, budget: CollectBudget) -> None:
        self._budget = budget
        self.used = 0
        self.history_used = 0
        self.stopped = False  # set on HTTP 509: the stage must stop

    def spend(self) -> None:
        """Record a mandatory call (changeset, osmChange, user)."""
        self.used += 1

    def take(self, *, history: bool = False) -> bool:
        """Reserve one call; False when the total (or history) budget is spent or stopped."""
        if self.stopped or self.used >= self._budget.max_total_calls:
            return False
        if history:
            if self.history_used >= self._budget.max_history_calls:
                return False
            self.history_used += 1
        self.used += 1
        return True


@dataclass(slots=True)
class _Prior:
    """Outcome of reconstructing one element's prior version."""

    element: dict[str, Any] | None = None
    gap: CoverageGapReason | None = None
    history: list[dict[str, Any]] | None = None  # kept when fetched, for the age lookup


# ----------------------------------------------------------------------------- helpers


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _rank_key(el: GroupedElement) -> int:
    if el.action is ChangeAction.DELETE:
        return 0
    if el.action is ChangeAction.MODIFY:
        touches = any(k in PRIORITY_KEYS or k.startswith(PRIORITY_PREFIX) for k in el.last.tags)
        return 1 if touches else 2
    return 3


def _needs_prior(el: GroupedElement) -> bool:
    return el.action in (ChangeAction.MODIFY, ChangeAction.DELETE) and el.before_version is not None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(2 * EARTH_RADIUS_M * math.asin(math.sqrt(a)), 2)


def _tag_diffs(
    el: GroupedElement, before: dict[str, str] | None, after: dict[str, str] | None
) -> list[TagDiff]:
    if before is None and after is None:
        return []
    old, new = before or {}, after or {}
    diffs: list[TagDiff] = []
    for key in sorted(old.keys() | new.keys()):
        b, a = old.get(key), new.get(key)
        if b == a:
            continue
        change = (
            TagChange.ADDED if b is None else TagChange.REMOVED if a is None else TagChange.CHANGED
        )
        diffs.append(
            TagDiff(
                osm_type=el.osm_type, osm_id=el.osm_id, key=key, before=b, after=a, change=change
            )
        )
    return diffs


def _geometry_change(el: GroupedElement, prior: dict[str, Any] | None) -> GeometryChange | None:
    if prior is None or el.action is not ChangeAction.MODIFY:
        return None
    if el.osm_type is OsmType.NODE:
        lat, lon = prior.get("lat"), prior.get("lon")
        new_lat, new_lon = el.last.lat, el.last.lon
        if lat is None or lon is None or new_lat is None or new_lon is None:
            return None
        return GeometryChange(node_moved_m=_haversine_m(lat, lon, new_lat, new_lon))
    if el.osm_type is OsmType.WAY and isinstance(prior.get("nodes"), list):
        return GeometryChange(way_node_delta=len(el.last.nodes) - len(prior["nodes"]))
    return None


def _canonical_hash(payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _evidence_version(
    meta: ChangesetMeta,
    grouped: tuple[GroupedElement, ...],
    discussion_ids: list[int],
    fetched_at: datetime,
) -> str:
    """sha256 over changeset id, closed_at|open, max element versions seen, comment ids and, for
    open changesets, a fetched_at bucket (product-and-domain.md §identity)."""
    bucket = int(fetched_at.timestamp()) // OPEN_CHANGESET_BUCKET_S if meta.open else None
    return _canonical_hash(
        {
            "changeset_id": meta.id,
            "state": "open" if meta.open or meta.closed_at is None else meta.closed_at.isoformat(),
            "versions": sorted([e.osm_type.value, e.osm_id, e.after_version] for e in grouped),
            "discussion": sorted(discussion_ids),
            "bucket": bucket,
        }
    )


def _score(coverage_detailed: int, needing: int, gaps: int, user: FetchStatus) -> float:
    gap_ratio = gaps / max(1, coverage_detailed)
    value = coverage_detailed / max(1, needing) * (1 - gap_ratio)
    if user is not FetchStatus.FETCHED:
        value *= 0.9
    return round(min(1.0, max(0.0, value)), 6)


# ----------------------------------------------------------------------------- fetching


async def _fetch_prior(
    source: OsmSource, el: GroupedElement, gate: _Gate, cache: PriorVersionCache | None
) -> _Prior:
    """Reconstruct v-1 of one element, with the 403 -> history fallback and typed gaps."""
    version = el.before_version
    if version is None:  # callers check _needs_prior; nothing to reconstruct
        return _Prior()
    key = (el.osm_type, el.osm_id, version)
    if cache is not None and (hit := cache.get(key)) is not None:
        return _Prior(element=hit)
    if not gate.take():
        return _Prior(gap=CoverageGapReason.BUDGET)
    try:
        element = await source.get_element_version(el.osm_type, el.osm_id, version)
    except Redacted403:
        return await _history_fallback(source, el, gate)
    except NotFoundError:
        return _Prior(gap=CoverageGapReason.NOT_FOUND)
    except OsmTimeoutError:
        return _Prior(gap=CoverageGapReason.TIMEOUT)
    except BandwidthLimitError:
        gate.stopped = True
        return _Prior(gap=CoverageGapReason.BUDGET)
    except OsmError:
        return _Prior(gap=CoverageGapReason.TIMEOUT)
    if cache is not None:
        cache.put(key, element)
    return _Prior(element=element)


async def _history_fallback(source: OsmSource, el: GroupedElement, gate: _Gate) -> _Prior:
    """Highest visible version below this changeset's first version, else a redacted gap."""
    if not gate.take(history=True):
        return _Prior(gap=CoverageGapReason.REDACTED)
    try:
        history = await source.get_element_history(el.osm_type, el.osm_id)
    except OsmTimeoutError:
        return _Prior(gap=CoverageGapReason.TIMEOUT)
    except BandwidthLimitError:
        gate.stopped = True
        return _Prior(gap=CoverageGapReason.BUDGET)
    except NotFoundError:
        return _Prior(gap=CoverageGapReason.REDACTED)
    except OsmError:
        return _Prior(gap=CoverageGapReason.TIMEOUT)
    older = [
        h for h in history if h.get("visible", True) and int(h.get("version", 0)) < el.first.version
    ]
    if not older:
        return _Prior(gap=CoverageGapReason.REDACTED, history=history)
    return _Prior(element=max(older, key=lambda h: int(h["version"])), history=history)


@dataclass(frozen=True, slots=True)
class _FirstVersion:
    """What the first version of an element tells us: when it was created and by whom."""

    timestamp: datetime | None = None
    uid: int | None = None


def _as_uid(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _from_first(element: dict[str, Any]) -> _FirstVersion:
    return _FirstVersion(_parse_ts(element.get("timestamp")), _as_uid(element.get("uid")))


async def _first_version(
    source: OsmSource, el: GroupedElement, prior: _Prior, gate: _Gate
) -> _FirstVersion:
    """Timestamp and creator uid of version 1: free when v-1 is v1, else one history call.

    Both come from data already fetched for the age lookup, so creator uids add no calls.
    """
    if prior.element is None:
        return _FirstVersion()
    if int(prior.element.get("version", 0)) == 1:
        return _from_first(prior.element)
    history = prior.history
    if history is None:
        if not gate.take(history=True):
            return _FirstVersion()
        try:
            history = await source.get_element_history(el.osm_type, el.osm_id)
        except BandwidthLimitError:
            gate.stopped = True
            return _FirstVersion()
        except OsmError:
            return _FirstVersion()
    for h in history:
        if int(h.get("version", 0)) == 1:
            return _from_first(h)
    return _FirstVersion()


async def _fetch_user(
    source: OsmSource, meta: ChangesetMeta, gate: _Gate
) -> tuple[UserFacts | None, dict[str, Any] | None, FetchStatus]:
    if meta.uid is None:
        return None, None, FetchStatus.SKIPPED  # anonymous or deleted author
    gate.spend()
    try:
        raw = await source.get_user(meta.uid)
        user = apply_edit_time_count(user_from_api(raw, as_of=meta.created_at), meta)
        return user, raw, FetchStatus.FETCHED
    except BandwidthLimitError:
        gate.stopped = True
    except (OsmError, ValueError) as exc:  # FixtureError is a ValueError: unexpected user shape
        log.warning("osm.user_failed", changeset_id=meta.id, error=type(exc).__name__)
    return None, None, FetchStatus.FAILED


# ----------------------------------------------------------------------------- entry point


@dataclass(slots=True)
class _Detail:
    """Per-element working state while building the snapshot."""

    el: GroupedElement
    prior: _Prior | None = None
    first_ts: datetime | None = None
    creator_uid: int | None = None
    resolved: bool = False
    gap: CoverageGapReason | None = field(default=None)


async def collect(
    source: OsmSource,
    changeset_id: int,
    budget: CollectBudget | None = None,
    *,
    cache: PriorVersionCache | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EvidenceSnapshot:
    """Build an EvidenceSnapshot for one changeset.

    Raises OsmError subclasses only for fatal failures (changeset missing, osmChange unreadable or
    unsafe, 509 on the first calls); everything else degrades into `coverage`.
    """
    budget = budget or CollectBudget()
    gate = _Gate(budget)
    fetched_at = clock()
    is_replay = isinstance(source, ReplayClient)
    evidence_source = EvidenceSource.REPLAY if is_replay else EvidenceSource.OSM_API

    gate.spend()
    meta_raw = await source.get_changeset(changeset_id)
    meta = changeset_from_api(meta_raw)
    discussion = discussion_from_api(meta_raw)
    raw_comments = (meta_raw.get("changeset") or {}).get("comments")
    discussion_status = (
        FetchStatus.FETCHED
        if raw_comments is not None or meta.comments_count == 0
        else FetchStatus.FAILED
    )

    parsed: ParsedOsmChange | None = None
    gate.spend()
    try:
        parsed = parse_osm_change(await source.get_osc(changeset_id))
    except TooLargeError:  # includes ElementCapExceededError
        pass  # too large for a second opinion: snapshot_truncated, lane insufficient_evidence

    user, user_raw, user_status = await _fetch_user(source, meta, gate)

    flags: list[str] = []
    try:
        flags = compute_flags(
            meta_raw,
            action_counts=parsed.action_counts if parsed else None,
            user_raw=user_raw,
        )
    except FlagsUnavailableError as exc:
        log.warning("osm.flags_unavailable", error=str(exc))

    if parsed is None:  # truncated snapshot: honest coverage, no element detail
        total = meta.changes_count
        coverage = Coverage(
            elements_in_changeset=total,
            elements_detailed=0,
            elements_skipped_budget=total,
            user_profile=user_status,
            discussion=discussion_status,
            snapshot_truncated=True,
            score=0.0,
        )
        return EvidenceSnapshot(
            evidence_version=_evidence_version(meta, (), [d.id for d in discussion], fetched_at),
            source=evidence_source,
            fetched_at=fetched_at,
            provisional=meta.open,
            changeset=meta,
            user=user,
            coverage=coverage,
            discussion=discussion,
            flags=flags,
        )

    ranked = sorted(parsed.elements, key=_rank_key)  # stable: ties keep document order
    details = [_Detail(el) for el in ranked[: budget.max_elements_detailed]]
    await _reconstruct(source, details, gate, budget, cache)

    elements: list[ChangedObject] = []
    tag_diffs: list[TagDiff] = []
    gaps: list[HistoryGap] = []
    for d in details:
        el = d.el
        before_el = d.prior.element if d.prior else None
        before_tags: dict[str, str] | None = None
        if before_el is not None:
            before_tags = {str(k): str(v) for k, v in (before_el.get("tags") or {}).items()}
        after_tags = None if el.action is ChangeAction.DELETE else dict(el.last.tags)
        if el.action is ChangeAction.CREATE:
            before_tags = None
        reason = d.gap or (d.prior.gap if d.prior else None)
        if reason is not None:
            gaps.append(HistoryGap(osm_type=el.osm_type, osm_id=el.osm_id, reason=reason))
        age = None
        if d.first_ts is not None:
            age = max(0, (meta.created_at - d.first_ts).days)
        # Created inside this changeset (version 1): the changeset's own account is the creator.
        creator = meta.uid if el.first.version == 1 else d.creator_uid
        elements.append(
            ChangedObject(
                osm_type=el.osm_type,
                osm_id=el.osm_id,
                action=el.action,
                version_after=el.after_version,
                version_before=int(before_el["version"]) if before_el is not None else None,
                tags_before=before_tags,
                tags_after=after_tags,
                created_at_first_version=d.first_ts,
                created_by_uid=creator,
                age_days=age,
                geometry_change=_geometry_change(el, before_el),
                source=evidence_source,
            )
        )
        if before_tags is not None or not _needs_prior(el):  # unknown prior tags -> no diffs
            tag_diffs.extend(_tag_diffs(el, before_tags, after_tags))

    detailed = len(details)
    coverage = Coverage(
        elements_in_changeset=parsed.raw_element_count,
        elements_detailed=detailed,
        elements_skipped_budget=max(0, len(parsed.elements) - detailed),
        history_gaps=gaps,
        user_profile=user_status,
        discussion=discussion_status,
        snapshot_truncated=False,
        score=_score(detailed, len(parsed.elements), len(gaps), user_status),
    )
    return EvidenceSnapshot(
        evidence_version=_evidence_version(
            meta, parsed.elements, [d.id for d in discussion], fetched_at
        ),
        source=evidence_source,
        fetched_at=fetched_at,
        provisional=meta.open,
        changeset=meta,
        user=user,
        coverage=coverage,
        elements=elements,
        tag_diffs=tag_diffs,
        discussion=discussion,
        flags=flags,
        element_counts={a: n for a, n in parsed.action_counts.items() if n},
    )


async def _reconstruct(
    source: OsmSource,
    details: list[_Detail],
    gate: _Gate,
    budget: CollectBudget,
    cache: PriorVersionCache | None,
) -> None:
    """Fetch priors (pass 1) then ages from leftover history budget (pass 2), under the stage clock.

    Whatever has not completed when the stage clock expires is recorded as a timeout gap.
    """

    async def one(d: _Detail) -> None:
        d.prior = await _fetch_prior(source, d.el, gate, cache)
        d.resolved = True

    with anyio.move_on_after(budget.stage_timeout_s):
        async with anyio.create_task_group() as tg:
            for d in details:
                if _needs_prior(d.el):
                    tg.start_soon(one, d)
                else:
                    d.resolved = True
        for d in details:  # pass 2: age, rank order, only from what is left of the history budget
            if d.prior is not None and d.prior.element is not None:
                first = await _first_version(source, d.el, d.prior, gate)
                d.first_ts, d.creator_uid = first.timestamp, first.uid
    for d in details:
        if not d.resolved:
            d.gap = CoverageGapReason.TIMEOUT

"""Gather candidate changesets for labelling (read-only GETs, bounded and polite).

Two sources: MapRoulette challenge tasks (weak labels only) and recent changesets by new
accounts, found by listing recent closed changesets and keeping authors whose account is young.
Every candidate is collected through the OSM adapter (so its flags and coverage are computed the
same way as in the product) and its snapshot is cached locally for labelling and runs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import anyio

from cso.adapters.osm import MapRouletteClient, OsmClient
from cso.adapters.osm.client import OSM_API_BASE
from cso.adapters.osm.errors import OsmError
from cso.adapters.osm.maproulette import RouletteTask
from cso.domain.fixtures import user_from_api
from cso.evaluation.candidates_io import (
    SOURCE_MAPROULETTE,
    SOURCE_RECENT_NEW,
    Candidate,
    candidate_from_snapshot,
)
from cso.evaluation.snapshots import SnapshotCache, snapshot_for

MAPROULETTE_CHALLENGE = 55814
MAX_CANDIDATES = 200
POLITE_PAUSE_S = 0.25
NEW_ACCOUNT_MAX_AGE_DAYS = 30
RECENT_SCAN = 100


@dataclass
class GatherReport:
    """What a gathering run did, for the report line and the tests."""

    maproulette_tasks: int = 0
    maproulette_collected: int = 0
    recent_scanned: int = 0
    recent_new_accounts: int = 0
    recent_collected: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    stopped_early: bool = False
    candidates: list[Candidate] = field(default_factory=list)

    def error(self, code: str) -> None:
        self.errors[code] = self.errors.get(code, 0) + 1


async def _recent_new_account_ids(osm: OsmClient, report: GatherReport, want: int) -> list[int]:
    """Recent closed changesets whose author account is younger than 30 days."""
    data = await osm.get_json(
        f"{OSM_API_BASE}/changesets.json", params={"limit": str(RECENT_SCAN), "closed": "true"}
    )
    changesets = data.get("changesets", []) if isinstance(data, dict) else []
    by_uid: dict[int, list[int]] = {}
    for item in changesets:
        uid, cs = item.get("uid"), item.get("id")
        if isinstance(uid, int) and isinstance(cs, int) and item.get("changes_count", 0) > 0:
            by_uid.setdefault(uid, []).append(cs)
    report.recent_scanned = len(changesets)
    picked: list[int] = []
    now = datetime.now(UTC)
    for uid, ids in by_uid.items():
        if len(picked) >= want:
            break
        try:
            facts = user_from_api(await osm.get_user(uid), as_of=now)
        except OsmError:
            report.error("user_fetch")
            continue
        await anyio.sleep(POLITE_PAUSE_S)
        if facts.account_age_days is not None and facts.account_age_days < NEW_ACCOUNT_MAX_AGE_DAYS:
            report.recent_new_accounts += 1
            picked.append(ids[0])
    return picked


async def gather(
    osm: OsmClient,
    roulette: MapRouletteClient,
    cache: SnapshotCache,
    *,
    limit: int = MAX_CANDIDATES,
    challenge_id: int = MAPROULETTE_CHALLENGE,
    max_minutes: float = 25.0,
    progress: Callable[[str], None] = lambda _msg: None,
    clock: Callable[[], float] = time.monotonic,
) -> GatherReport:
    """Collect up to `limit` (<= 200) candidates; stops early when `max_minutes` is exceeded."""
    limit = max(0, min(limit, MAX_CANDIDATES))
    report = GatherReport()
    deadline = clock() + max_minutes * 60
    seen: set[int] = set()

    async def take(cs: int, source: str, mr_status: int | None) -> bool:
        if cs in seen:
            return False
        seen.add(cs)
        try:
            snapshot = await snapshot_for(osm, cs, cache)
        except OsmError as exc:
            report.error(type(exc).__name__)
            return False
        report.candidates.append(
            candidate_from_snapshot(snapshot, source=source, mr_status=mr_status)
        )
        await anyio.sleep(POLITE_PAUSE_S)
        return True

    # Source 1: MapRoulette (weak labels) fills first; recent changesets fill what is left.
    mr_target = limit
    tasks: list[RouletteTask] = []
    try:
        tasks = await roulette.list_challenge_tasks(challenge_id, limit=min(1000, limit * 4))
    except OsmError as exc:
        report.error(f"maproulette:{type(exc).__name__}")
    report.maproulette_tasks = len(tasks)
    for task in tasks:
        if report.maproulette_collected >= mr_target or clock() > deadline:
            report.stopped_early = report.stopped_early or clock() > deadline
            break
        if await take(task["changeset_id"], SOURCE_MAPROULETTE, task["status"]):
            report.maproulette_collected += 1
            if report.maproulette_collected % 10 == 0:
                progress(f"maproulette: {report.maproulette_collected}/{mr_target}")

    # Source 2: recent changesets by new accounts, filling up to the limit.
    remaining = limit - len(report.candidates)
    if remaining > 0 and clock() <= deadline:
        try:
            ids = await _recent_new_account_ids(osm, report, remaining)
        except OsmError as exc:
            ids = []
            report.error(f"recent:{type(exc).__name__}")
        for cs in ids:
            if len(report.candidates) >= limit or clock() > deadline:
                report.stopped_early = report.stopped_early or clock() > deadline
                break
            if await take(cs, SOURCE_RECENT_NEW, None):
                report.recent_collected += 1
    return report


def candidate_rows(candidates: list[Candidate]) -> list[dict[str, Any]]:
    """JSON rows for evaluation/candidates.jsonl, ordered by changeset id."""
    return [c.to_json() for c in sorted(candidates, key=lambda c: c.changeset_id)]

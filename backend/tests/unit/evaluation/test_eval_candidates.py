from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cso.adapters.osm import ReplayClient, collect
from cso.adapters.osm.maproulette import RouletteTask
from cso.domain.fixtures import load_case
from cso.evaluation.candidates import MAX_CANDIDATES, gather
from cso.evaluation.snapshots import SnapshotCache

CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"


async def _warm_cache(tmp_path: Path) -> tuple[SnapshotCache, list[int], dict[int, str]]:
    cache = SnapshotCache(tmp_path / "snaps")
    ids: list[int] = []
    names: dict[int, str] = {}
    for case_dir in sorted(CASES.iterdir()):
        cs = load_case(case_dir).expected.changeset_id
        snapshot = await collect(ReplayClient(case_dir), cs)
        cache.put(snapshot)
        ids.append(cs)
        names[cs] = snapshot.changeset.user_display or ""
    return cache, ids, names


class FakeRoulette:
    def __init__(self, tasks: list[RouletteTask]) -> None:
        self.tasks = tasks
        self.asked: list[tuple[int, int]] = []

    async def list_challenge_tasks(self, challenge_id: int, limit: int = 50) -> list[RouletteTask]:
        self.asked.append((challenge_id, limit))
        return self.tasks


class FakeOsm:
    """Only the read calls `gather` makes; the cache is warm so no evidence is fetched."""

    def __init__(self, recent: list[dict[str, Any]], account_age_days: dict[int, int]) -> None:
        self.recent = recent
        self.ages = account_age_days
        self.requested: list[str] = []

    async def get_json(self, url: str, *, params: dict[str, str] | None = None) -> Any:
        self.requested.append(url)
        return {"changesets": self.recent}

    async def get_user(self, uid: int) -> dict[str, Any]:
        from datetime import UTC, datetime, timedelta

        created = datetime.now(UTC) - timedelta(days=self.ages[uid])
        return {
            "user": {
                "id": uid,
                "display_name": f"real_name_{uid}",
                "account_created": created.isoformat(),
                "changesets": {"count": 1},
                "blocks": {"received": {"active": 0}},
            }
        }


async def test_gather_uses_the_challenge_and_writes_anonymised_candidates(tmp_path: Path) -> None:
    cache, ids, names = await _warm_cache(tmp_path)
    tasks: list[RouletteTask] = [
        {"changeset_id": cs, "status": 1 if i % 2 else 2, "task_id": 500 + i}
        for i, cs in enumerate(ids)
    ]
    roulette = FakeRoulette(tasks)
    osm = FakeOsm(recent=[], account_age_days={})
    report = await gather(osm, roulette, cache, limit=200, max_minutes=1)  # type: ignore[arg-type]
    assert roulette.asked[0][0] == 55814
    assert report.maproulette_tasks == len(ids)
    assert 0 < report.maproulette_collected <= len(ids)
    assert len(report.candidates) == report.maproulette_collected
    blob = json.dumps([c.to_json() for c in report.candidates])
    for name in names.values():
        if name:
            assert name not in blob  # no display names in candidate rows
    assert all(c.weak_mr_status in ("fixed", "false_positive") for c in report.candidates)
    assert all(len(c.mapper_hash) == 16 for c in report.candidates)


async def test_gather_never_exceeds_the_hard_limit_and_dedupes(tmp_path: Path) -> None:
    cache, ids, _ = await _warm_cache(tmp_path)
    tasks: list[RouletteTask] = [
        {"changeset_id": ids[0], "status": 1, "task_id": n} for n in range(50)
    ] + [{"changeset_id": cs, "status": 2, "task_id": 900 + cs % 100} for cs in ids]
    report = await gather(
        FakeOsm([], {}),
        FakeRoulette(tasks),
        cache,
        limit=3,
        max_minutes=1,  # type: ignore[arg-type]
    )
    assert len(report.candidates) <= 3
    assert len({c.changeset_id for c in report.candidates}) == len(report.candidates)
    assert MAX_CANDIDATES == 200
    over = await gather(
        FakeOsm([], {}),
        FakeRoulette(tasks),
        cache,
        limit=10_000,
        max_minutes=1,  # type: ignore[arg-type]
    )
    assert len(over.candidates) <= MAX_CANDIDATES


async def test_gather_stops_when_the_time_budget_is_spent(tmp_path: Path) -> None:
    cache, ids, _ = await _warm_cache(tmp_path)
    tasks: list[RouletteTask] = [
        {"changeset_id": cs, "status": 1, "task_id": i} for i, cs in enumerate(ids)
    ]
    ticks = iter(range(0, 10_000, 1000))
    report = await gather(
        FakeOsm([], {}),
        FakeRoulette(tasks),
        cache,
        limit=200,
        max_minutes=1,  # type: ignore[arg-type]
        clock=lambda: float(next(ticks)),
    )
    assert report.stopped_early


async def test_recent_changesets_keep_only_new_accounts(tmp_path: Path) -> None:
    cache, ids, _ = await _warm_cache(tmp_path)
    recent = [
        {"id": ids[0], "uid": 7, "changes_count": 3},  # account 5 days old: kept
        {"id": ids[1], "uid": 8, "changes_count": 3},  # account 400 days old: dropped
        {"id": ids[2], "uid": 9, "changes_count": 0},  # nothing changed: dropped
    ]
    osm = FakeOsm(recent=recent, account_age_days={7: 5, 8: 400, 9: 2})
    report = await gather(osm, FakeRoulette([]), cache, limit=200, max_minutes=1)  # type: ignore[arg-type]
    assert report.recent_scanned == 3
    assert report.recent_new_accounts == 1
    assert [c.changeset_id for c in report.candidates] == [ids[0]]
    assert report.candidates[0].source == "recent_new_accounts"
    assert osm.requested and all("changesets.json" in u for u in osm.requested)

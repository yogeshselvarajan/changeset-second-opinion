"""Backfill of edit-time changeset counts into the local snapshot cache (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from cso.adapters.osm import OsmError, ReplayClient, collect
from cso.adapters.osm.errors import NotFoundError
from cso.domain.models import EvidenceSnapshot
from cso.evaluation.backfill import backfill, patch_snapshot, render_report
from cso.evaluation.panel_compare import compare, render_section
from cso.evaluation.snapshots import SnapshotCache

CASES = Path(__file__).parents[3] / "fixtures" / "cases"


class FakeSource:
    """Serves `changeset.json` envelopes by id; counts calls; may fail for chosen ids."""

    def __init__(self, tags_by_id: dict[int, dict[str, str]], fail: set[int] | None = None) -> None:
        self.tags_by_id = tags_by_id
        self.fail = fail or set()
        self.calls: list[int] = []

    async def get_changeset(self, changeset_id: int) -> dict[str, object]:
        self.calls.append(changeset_id)
        if changeset_id in self.fail:
            raise NotFoundError("gone")
        return {"changeset": {"id": changeset_id, "tags": self.tags_by_id.get(changeset_id, {})}}


async def legacy_snapshot(name: str, *, current_total: int) -> EvidenceSnapshot:
    """A snapshot as the cache held it before the fix: current total, no basis, no tag."""
    client = ReplayClient(CASES / name)
    snapshot = await collect(client, client.case.changeset.id)
    assert snapshot.user is not None
    user = snapshot.user.model_copy(
        update={"changesets_count": current_total, "changesets_count_basis": None}
    )
    meta = snapshot.changeset.model_copy(update={"changesets_count": None})
    return snapshot.model_copy(update={"user": user, "changeset": meta})


def run(coro: object) -> object:
    async def inner() -> object:
        return await coro  # type: ignore[misc]

    return anyio.run(inner)


async def seeded_cache(tmp_path: Path) -> tuple[SnapshotCache, EvidenceSnapshot, EvidenceSnapshot]:
    cache = SnapshotCache(tmp_path)
    a = await legacy_snapshot("01-legitimate", current_total=29)
    b = await legacy_snapshot("08-adversarial-text", current_total=120)
    cache.put(a)
    cache.put(b)
    return cache, a, b


async def test_patch_uses_the_tag_and_labels_the_basis(tmp_path: Path) -> None:
    _, a, _ = await seeded_cache(tmp_path)
    patched = patch_snapshot(a, {"changeset": {"tags": {"changesets_count": "5"}}})
    assert patched.changeset.changesets_count == 5
    assert patched.user is not None
    assert (patched.user.changesets_count, patched.user.changesets_count_basis) == (5, "edit_time")


async def test_patch_without_the_tag_keeps_the_total_as_current(tmp_path: Path) -> None:
    _, a, _ = await seeded_cache(tmp_path)
    patched = patch_snapshot(a, {"changeset": {"tags": {"comment": "x"}}})
    assert patched.changeset.changesets_count is None
    assert patched.user is not None
    assert (patched.user.changesets_count, patched.user.changesets_count_basis) == (29, "current")


@pytest.mark.parametrize("raw", [{}, {"changeset": None}, {"changeset": {"tags": "x"}}])
async def test_patch_tolerates_odd_shapes(tmp_path: Path, raw: dict[str, object]) -> None:
    _, a, _ = await seeded_cache(tmp_path)
    patched = patch_snapshot(a, raw)
    assert patched.changeset.changesets_count is None


async def test_backfill_patches_the_cache_with_one_get_each(tmp_path: Path) -> None:
    cache, a, b = await seeded_cache(tmp_path)
    source = FakeSource({a.changeset.id: {"changesets_count": "5"}})
    report = await backfill(source, cache)  # type: ignore[arg-type]
    assert sorted(source.calls) == sorted([a.changeset.id, b.changeset.id])
    assert (report.total, report.with_tag, report.without_tag, report.failed) == (2, 1, 1, 0)
    first, second = cache.get(a.changeset.id), cache.get(b.changeset.id)
    assert first is not None and first.user is not None
    assert (first.user.changesets_count, first.user.changesets_count_basis) == (5, "edit_time")
    assert second is not None and second.user is not None
    assert (second.user.changesets_count, second.user.changesets_count_basis) == (120, "current")


async def test_backfill_is_idempotent_and_skips_finished_items(tmp_path: Path) -> None:
    cache, a, b = await seeded_cache(tmp_path)
    source = FakeSource({a.changeset.id: {"changesets_count": "5"}})
    await backfill(source, cache)  # type: ignore[arg-type]
    again = FakeSource({})
    report = await backfill(again, cache)  # type: ignore[arg-type]
    assert again.calls == []
    assert report.already_done == 2 and report.with_tag == 0


async def test_failed_fetch_leaves_the_snapshot_untouched(tmp_path: Path) -> None:
    cache, a, b = await seeded_cache(tmp_path)
    before = cache.get(b.changeset.id)
    report = await backfill(FakeSource({}, fail={b.changeset.id}), cache)  # type: ignore[arg-type]
    assert report.failed == 1
    assert cache.get(b.changeset.id) == before
    assert issubclass(NotFoundError, OsmError)


async def test_report_counts_the_fact_change_and_names_nobody(tmp_path: Path) -> None:
    cache, a, b = await seeded_cache(tmp_path)
    # account 01 is old (age >= 7): current 29 -> unknown; edit-time 5 -> true
    report = await backfill(FakeSource({a.changeset.id: {"changesets_count": "5"}}), cache)  # type: ignore[arg-type]
    assert report.count_changed == 1
    text = render_report(report, date="2026-10-17")
    assert "cached snapshots | 2" in text
    snapshot = cache.get(a.changeset.id)
    assert snapshot is not None and snapshot.user is not None
    assert str(snapshot.user.display_name) not in text


async def test_labels_are_never_touched(tmp_path: Path) -> None:
    labels = Path(__file__).parents[4] / "evaluation" / "labels" / "dev.jsonl"
    before = labels.read_bytes() if labels.exists() else b""
    cache, a, _ = await seeded_cache(tmp_path)
    await backfill(FakeSource({a.changeset.id: {"changesets_count": "5"}}), cache)  # type: ignore[arg-type]
    assert (labels.read_bytes() if labels.exists() else b"") == before


# --------------------------------------------------------------- before / after compare


def write_receipt(directory: Path, cs: int, state: str, probability: float, check: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "changeset_id": cs,
        "panel": {
            "readings": {"new_account_first_edits": {"state": state, "probability": probability}}
        },
        "composition": {"cross_checks": {"new_account_first_edits": check}},
    }
    (directory / f"{cs}.json").write_text(json.dumps(data), encoding="utf-8")


def test_compare_counts_states_and_cross_checks(tmp_path: Path) -> None:
    before, after = tmp_path / "before", tmp_path / "after"
    write_receipt(before, 1, "yes", 0.9, "agree")
    write_receipt(before, 2, "yes", 0.8, "disagree")
    write_receipt(before, 3, "no", 0.1, "agree")
    write_receipt(after, 1, "yes", 0.9, "agree")
    write_receipt(after, 2, "unknown", 0.5, "undecided")
    write_receipt(after, 3, "no", 0.1, "agree")
    write_receipt(after, 4, "yes", 0.7, "agree")  # only in the new run
    write_receipt(before, 5, "no", 0.2, "agree")
    write_receipt(after, 5, "no", 0.2, "n/a")  # the parsed fact became unknown after the fix
    result = compare(before, after)
    assert result.items_both == 4
    assert (result.state_changed, result.cross_check_changed) == (1, 2)
    assert result.after.cross_checks["n/a"] == 1 and result.before.cross_checks["n/a"] == 0
    assert result.before.states["yes"] == 2 and result.after.states["unknown"] == 1
    text = render_section(result)
    assert "Before vs after" in text and "new_account_first_edits" in text
    assert "| read unknown | 0 | 1 |" in text

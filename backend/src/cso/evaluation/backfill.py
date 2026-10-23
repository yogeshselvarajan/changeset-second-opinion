"""Backfill edit-time changeset counts into cached evidence snapshots.

Early snapshots show the author's *current* changeset total, not the count when the edit was made.
The changeset's own `changesets_count` tag has the edit-time value (some editors publish it). One
read-only GET per cached changeset patches the local cache; nothing is invented when the tag is
missing. The cache is local and never committed, and no label file is touched.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cso.adapters.osm import OsmError, OsmSource
from cso.domain.fixtures import apply_edit_time_count, parse_edit_time_count
from cso.domain.models import EvidenceSnapshot
from cso.domain.policy import new_account_first_edits
from cso.evaluation.snapshots import SnapshotCache


@dataclass(slots=True)
class BackfillReport:
    """Counts only (no names): what the backfill found and changed."""

    total: int = 0
    already_done: int = 0
    with_tag: int = 0
    without_tag: int = 0
    failed: int = 0
    count_changed: int = 0  # the edit-time count differs from the stored current total
    new_account_before: int = 0  # parsed fact True before the patch
    new_account_after: int = 0  # parsed fact True after the patch
    new_account_unknown_after: int = 0  # parsed fact None after the patch
    fact_changed: int = 0  # parsed fact differs before vs after


def _is_done(snapshot: EvidenceSnapshot) -> bool:
    user = snapshot.user
    return snapshot.changeset.changesets_count is not None or (
        user is not None and user.changesets_count_basis is not None
    )


def patch_snapshot(
    snapshot: EvidenceSnapshot, raw_changeset: dict[str, object]
) -> EvidenceSnapshot:
    """The snapshot with the edit-time count applied (pure; no network)."""
    changeset_obj = raw_changeset.get("changeset")
    tags = changeset_obj.get("tags") if isinstance(changeset_obj, dict) else None
    count = parse_edit_time_count(tags if isinstance(tags, dict) else {})
    meta = snapshot.changeset.model_copy(update={"changesets_count": count})
    user = apply_edit_time_count(snapshot.user, meta)
    return snapshot.model_copy(update={"changeset": meta, "user": user})


async def backfill(
    source: OsmSource,
    cache: SnapshotCache,
    *,
    progress: Callable[[str], None] | None = None,
) -> BackfillReport:
    """Patch every cached snapshot; one `GET changeset` each, sequentially (polite)."""
    report = BackfillReport()
    ids = sorted(int(p.stem) for p in cache.directory.glob("*.json") if p.stem.isdigit())
    for changeset_id in ids:
        snapshot = cache.get(changeset_id)
        if snapshot is None:
            continue
        report.total += 1
        if _is_done(snapshot):
            report.already_done += 1
            continue
        try:
            raw = await source.get_changeset(changeset_id)
        except OsmError:
            report.failed += 1
            continue
        patched = patch_snapshot(snapshot, raw)
        if patched.changeset.changesets_count is None:
            report.without_tag += 1
        else:
            report.with_tag += 1
        before_user = snapshot.user.changesets_count if snapshot.user else None
        after_user = patched.user.changesets_count if patched.user else None
        if patched.changeset.changesets_count is not None and before_user != after_user:
            report.count_changed += 1
        before = new_account_first_edits(snapshot)
        after = new_account_first_edits(patched)
        report.new_account_before += before is True
        report.new_account_after += after is True
        report.new_account_unknown_after += after is None
        report.fact_changed += before != after
        cache.put(patched)
        if progress is not None and report.total % 20 == 0:
            progress(f"backfill: {report.total}/{len(ids)}")
    return report


def render_report(report: BackfillReport, *, date: str) -> str:
    """Markdown with counts only."""
    done = report.total - report.already_done - report.failed
    return (
        f"# Edit-time changeset count backfill ({date})\n\n"
        "Counts only; no names. The evidence used to show each author's current changeset total.\n"
        "The changeset's own `changesets_count` tag holds the count when the edit was made.\n\n"
        "| Measure | Items |\n|---|---|\n"
        f"| cached snapshots | {report.total} |\n"
        f"| already patched before this run | {report.already_done} |\n"
        f"| fetched this run | {done} |\n"
        f"| fetch failed (left unchanged) | {report.failed} |\n"
        f"| tag present: edit-time count used | {report.with_tag} |\n"
        f"| tag absent: current total kept, labelled `current` | {report.without_tag} |\n"
        f"| edit-time count differs from the stored total | {report.count_changed} |\n\n"
        "## Effect on the parsed `new_account` fact\n\n"
        "(account under 7 days old, or under 10 changesets at the time)\n\n"
        "| | Items |\n|---|---|\n"
        f"| true before the patch | {report.new_account_before} |\n"
        f"| true after the patch | {report.new_account_after} |\n"
        f"| unknown after the patch | {report.new_account_unknown_after} |\n"
        f"| fact differs before vs after | {report.fact_changed} |\n\n"
        "An unknown means only a current total of 10 or more is available, which cannot show the\n"
        "edit-time count was 10 or more. Unknown readings count as cautious in the composition.\n"
    )

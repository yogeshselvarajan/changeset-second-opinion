"""Local cache of collected evidence snapshots (never committed: they contain mapper names)."""

from __future__ import annotations

from pathlib import Path

from cso.adapters.osm import CollectBudget, OsmSource, PriorVersionCache, collect
from cso.domain.models import EvidenceSnapshot
from cso.evaluation.paths import write_text_lf


class SnapshotCache:
    """One JSON file per changeset under a directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, changeset_id: int) -> Path:
        return self.directory / f"{changeset_id}.json"

    def get(self, changeset_id: int) -> EvidenceSnapshot | None:
        path = self._path(changeset_id)
        if not path.exists():
            return None
        return EvidenceSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, snapshot: EvidenceSnapshot) -> None:
        write_text_lf(self._path(snapshot.changeset.id), snapshot.model_dump_json() + "\n")

    def has(self, changeset_id: int) -> bool:
        return self._path(changeset_id).exists()


async def snapshot_for(
    source: OsmSource | None,
    changeset_id: int,
    cache: SnapshotCache,
    *,
    budget: CollectBudget | None = None,
    prior_cache: PriorVersionCache | None = None,
) -> EvidenceSnapshot:
    """Cached snapshot, or a fresh collect() through `source` (stored in the cache).

    Raises LookupError when the snapshot is not cached and no source is given.
    """
    cached = cache.get(changeset_id)
    if cached is not None:
        return cached
    if source is None:
        raise LookupError(
            f"no cached evidence for changeset {changeset_id}; run `cso eval candidates` first"
        )
    snapshot = await collect(source, changeset_id, budget, cache=prior_cache)
    cache.put(snapshot)
    return snapshot

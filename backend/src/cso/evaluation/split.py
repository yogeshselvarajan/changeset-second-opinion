"""Group split into dev and held-out, with a frozen held-out id list.

Grouping is by mapper hash, so no mapper appears in both splits (and a changeset id belongs to
exactly one). The held-out list is written once with its sha256; loading it for a run needs
`released=True` and re-verifies the hash, so tuning on held-out data is refused.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cso.evaluation.candidates_io import Candidate
from cso.evaluation.paths import EvalPaths, iter_ids, write_text_lf

DEV = "dev"
HELDOUT = "heldout"
SPLIT_SEED = "cso-eval-split-v1"
SHA_FILE = "heldout_ids.sha256"


class SplitError(ValueError):
    """The split cannot be built or loaded."""


class HeldOutRefused(SplitError):
    """Held-out ids were requested without `--released`."""


class FreezeMismatch(SplitError):
    """The held-out id file no longer matches its committed hash."""


class AlreadyFrozen(SplitError):
    """A frozen split already exists and is never overwritten."""


@dataclass(frozen=True)
class Split:
    """Disjoint id sets; `reserve` holds candidates that fit in neither split."""

    dev: tuple[int, ...]
    heldout: tuple[int, ...]
    reserve: tuple[int, ...]


def ids_hash(ids: Sequence[int]) -> str:
    """sha256 over the sorted ids, one per line (the value stored in heldout_ids.sha256)."""
    payload = "".join(f"{i}\n" for i in sorted(ids))
    return hashlib.sha256(payload.encode()).hexdigest()


def _rank(key: str) -> str:
    return hashlib.sha256(f"{SPLIT_SEED}:{key}".encode()).hexdigest()


def build_split(
    candidates: Sequence[Candidate], dev_size: int = 60, heldout_size: int = 120
) -> Split:
    """Deterministic, mapper-grouped, stratum-interleaved split.

    Mapper groups are ordered by a seeded hash inside each stratum and the strata are interleaved
    round-robin, so both splits receive a similar mix of weak-signal strata. A group goes to dev
    while it fits, otherwise to held-out while it fits; what does not fit is `reserve`. Sizes are
    exact when the groups allow it; otherwise the split is smaller and the caller must check.
    """
    if dev_size < 0 or heldout_size < 0:
        raise SplitError("split sizes must be non-negative")
    by_mapper: dict[str, list[Candidate]] = defaultdict(list)
    seen: set[int] = set()
    for cand in candidates:
        if cand.changeset_id in seen:
            continue
        seen.add(cand.changeset_id)
        by_mapper[cand.mapper_hash].append(cand)

    strata: dict[str, list[str]] = defaultdict(list)
    for mapper, items in by_mapper.items():
        strata[items[0].stratum].append(mapper)
    queues = [sorted(group, key=_rank) for _, group in sorted(strata.items())]
    ordered: list[str] = []
    while any(queues):
        for queue in queues:
            if queue:
                ordered.append(queue.pop(0))

    dev: list[int] = []
    heldout: list[int] = []
    reserve: list[int] = []
    for mapper in ordered:
        ids = sorted(c.changeset_id for c in by_mapper[mapper])
        if len(dev) + len(ids) <= dev_size:
            dev.extend(ids)
        elif len(heldout) + len(ids) <= heldout_size:
            heldout.extend(ids)
        else:
            reserve.extend(ids)
    return Split(tuple(sorted(dev)), tuple(sorted(heldout)), tuple(sorted(reserve)))


def check_disjoint(split: Split, candidates: Sequence[Candidate]) -> None:
    """Raise `SplitError` if an id or a mapper appears in both dev and held-out."""
    if set(split.dev) & set(split.heldout):
        raise SplitError("a changeset id appears in both dev and heldout")
    mapper_of = {c.changeset_id: c.mapper_hash for c in candidates}
    dev_mappers = {mapper_of[i] for i in split.dev}
    held_mappers = {mapper_of[i] for i in split.heldout}
    if dev_mappers & held_mappers:
        raise SplitError("a mapper appears in both dev and heldout")


def write_frozen(paths: EvalPaths, split: Split) -> str:
    """Write the split files once; returns the held-out hash. Never overwrites a frozen split."""
    sha_path = paths.splits_dir / SHA_FILE
    if sha_path.exists() or (paths.splits_dir / "heldout_ids.txt").exists():
        raise AlreadyFrozen(
            f"{sha_path} exists: the held-out list is frozen and is never regenerated. "
            "Delete the splits directory by hand only if you accept restarting the evaluation."
        )
    digest = ids_hash(split.heldout)
    write_text_lf(paths.splits_dir / "dev_ids.txt", "".join(f"{i}\n" for i in split.dev))
    write_text_lf(
        paths.splits_dir / "heldout_ids.txt", "".join(f"{i}\n" for i in sorted(split.heldout))
    )
    write_text_lf(paths.splits_dir / "reserve_ids.txt", "".join(f"{i}\n" for i in split.reserve))
    write_text_lf(
        paths.splits_dir / "split-meta.json",
        json.dumps(
            {
                "seed": SPLIT_SEED,
                "dev": len(split.dev),
                "heldout": len(split.heldout),
                "reserve": len(split.reserve),
                "heldout_sha256": digest,
            },
            indent=2,
        )
        + "\n",
    )
    write_text_lf(sha_path, digest + "\n")
    return digest


def load_ids(paths: EvalPaths, set_name: str, *, released: bool = False) -> list[int]:
    """Ids of `dev` or `heldout`. Held-out needs `released=True` and a matching frozen hash."""
    if set_name == DEV:
        path = paths.splits_dir / "dev_ids.txt"
        if not path.exists():
            raise SplitError(f"{path} not found; run `cso eval split` first")
        return list(iter_ids(path))
    if set_name == HELDOUT:
        if not released:
            raise HeldOutRefused(
                "the held-out set is frozen: pass --released after the freeze commit "
                "(and only for the one final evaluation run)"
            )
        path = paths.splits_dir / "heldout_ids.txt"
        sha_path = paths.splits_dir / SHA_FILE
        if not path.exists() or not sha_path.exists():
            raise SplitError("no frozen held-out split; run `cso eval split` first")
        ids = list(iter_ids(path))
        if ids_hash(ids) != sha_path.read_text(encoding="utf-8").strip():
            raise FreezeMismatch("heldout_ids.txt does not match heldout_ids.sha256")
        return ids
    raise SplitError(f"unknown set {set_name!r}; expected 'dev' or 'heldout'")


def splits_exist(paths: Path) -> bool:
    """True if a frozen split is present under `paths` (an evaluation directory root)."""
    return (paths / "splits" / SHA_FILE).exists()

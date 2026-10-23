from __future__ import annotations

from pathlib import Path

import pytest

from cso.evaluation.candidates_io import Candidate, age_bucket, mapper_hash
from cso.evaluation.paths import EvalPaths
from cso.evaluation.split import (
    AlreadyFrozen,
    FreezeMismatch,
    HeldOutRefused,
    SplitError,
    build_split,
    check_disjoint,
    ids_hash,
    load_ids,
    write_frozen,
)

STRATA = [
    dict(flags=("mass deletion",), deletes=3, account_age="ge1y", weak_mr_status=None),
    dict(flags=("New mapper",), deletes=0, account_age="lt7d", weak_mr_status=None),
    dict(flags=(), deletes=0, account_age="ge1y", weak_mr_status="fixed"),
    dict(flags=(), deletes=0, account_age="ge1y", weak_mr_status="false_positive"),
    dict(flags=(), deletes=0, account_age="ge1y", weak_mr_status=None),
]


def _candidates(n_mappers: int = 120, per_mapper: int = 2) -> list[Candidate]:
    out: list[Candidate] = []
    cs = 1_000
    for m in range(n_mappers):
        kw = STRATA[m % len(STRATA)]
        for _ in range(per_mapper):
            cs += 1
            out.append(
                Candidate(
                    changeset_id=cs,
                    mapper_hash=mapper_hash(m, cs),
                    source="maproulette",
                    coverage_score=1.0,
                    elements=3,
                    **kw,  # type: ignore[arg-type]
                )
            )
    return out


def test_split_is_deterministic_disjoint_and_sized() -> None:
    cands = _candidates()
    a = build_split(cands, 60, 120)
    b = build_split(list(reversed(cands)), 60, 120)
    assert a == b
    assert (len(a.dev), len(a.heldout)) == (60, 120)
    assert not set(a.dev) & set(a.heldout)
    check_disjoint(a, cands)  # no changeset or mapper on both sides


def test_split_groups_by_mapper_even_when_mappers_have_many_changesets() -> None:
    cands = _candidates(n_mappers=30, per_mapper=7)
    split = build_split(cands, 60, 120)
    mapper_of = {c.changeset_id: c.mapper_hash for c in cands}
    dev_m = {mapper_of[i] for i in split.dev}
    held_m = {mapper_of[i] for i in split.heldout}
    assert dev_m.isdisjoint(held_m)
    assert len(split.dev) <= 60 and len(split.heldout) <= 120


def test_split_mixes_strata_into_dev() -> None:
    cands = _candidates()
    split = build_split(cands, 60, 120)
    by_id = {c.changeset_id: c for c in cands}
    assert len({by_id[i].stratum for i in split.dev}) >= 4


def test_check_disjoint_detects_a_shared_mapper() -> None:
    cands = _candidates(4, 1)
    shared = [Candidate(**{**c.__dict__, "mapper_hash": "same"}) for c in cands]
    from cso.evaluation.split import Split

    with pytest.raises(SplitError):
        check_disjoint(Split((shared[0].changeset_id,), (shared[1].changeset_id,), ()), shared)


def test_freeze_writes_once_and_never_overwrites(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    split = build_split(_candidates(), 60, 120)
    digest = write_frozen(paths, split)
    assert digest == ids_hash(split.heldout)
    assert (paths.splits_dir / "heldout_ids.sha256").read_text().strip() == digest
    assert b"\r" not in (paths.splits_dir / "heldout_ids.txt").read_bytes()
    with pytest.raises(AlreadyFrozen):
        write_frozen(paths, split)


def test_heldout_is_refused_without_released_and_verified_with_it(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    split = build_split(_candidates(), 60, 120)
    write_frozen(paths, split)
    assert load_ids(paths, "dev") == list(split.dev)  # dev never needs release
    with pytest.raises(HeldOutRefused):
        load_ids(paths, "heldout")
    assert load_ids(paths, "heldout", released=True) == sorted(split.heldout)


def test_tampering_with_the_frozen_heldout_list_is_detected(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    split = build_split(_candidates(), 60, 120)
    write_frozen(paths, split)
    held = paths.splits_dir / "heldout_ids.txt"
    held.write_text(held.read_text().replace(str(split.heldout[0]), "999999999", 1))
    with pytest.raises(FreezeMismatch):
        load_ids(paths, "heldout", released=True)


def test_unknown_set_and_missing_split_are_errors(tmp_path: Path) -> None:
    with pytest.raises(SplitError):
        load_ids(EvalPaths(tmp_path), "dev")
    with pytest.raises(SplitError):
        load_ids(EvalPaths(tmp_path), "other")


def test_candidates_never_expose_names_or_exact_ages() -> None:
    cand = _candidates(1, 1)[0]
    raw = cand.to_json()
    assert set(raw) == {
        "changeset_id",
        "mapper_hash",
        "source",
        "flags",
        "coverage_score",
        "elements",
        "deletes",
        "account_age",
        "weak_mr_status",
        "created_at",
    }
    assert age_bucket(3) == "lt7d" and age_bucket(400) == "ge1y" and age_bucket(None) == "unknown"
    assert len(raw["mapper_hash"]) == 16


def test_split_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cso.cli import main
    from cso.evaluation.paths import EVAL_DIR_ENV, write_text_lf

    paths = EvalPaths(tmp_path)
    write_text_lf(
        paths.candidates,
        "".join(__import__("json").dumps(c.to_json()) + "\n" for c in _candidates(100, 2)),
    )
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    assert main(["eval", "split", "--dry-run"]) == 0
    assert "dry run (nothing written)" in capsys.readouterr().out
    assert not paths.splits_dir.exists()
    assert main(["eval", "split"]) == 0  # the real split still works afterwards
    assert (paths.splits_dir / "heldout_ids.sha256").exists()

"""Every guard of the once-only held-out run, exercised against real temporary git repositories."""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path

import pytest
from heldout_support import CONFIG, FrozenRepo, git, make_frozen_repo

from cso.evaluation import eval_cli, heldout
from cso.evaluation.heldout import (
    HeldOutRequest,
    RunRefused,
    confirm_freeze,
    marker_path,
    prepare,
    refuse_if_already_run,
)
from cso.evaluation.paths import EVAL_DIR_ENV, EvalPaths

IDS = [900000000001, 900000000002, 900000000003]


@pytest.fixture(scope="module")
def shared(tmp_path_factory: pytest.TempPathFactory) -> FrozenRepo:
    """One frozen repo for the tests that only read it (git is slow to set up)."""
    return make_frozen_repo(tmp_path_factory.mktemp("shared"), IDS)


def request(frozen_commit: str | None, **over: object) -> HeldOutRequest:
    return HeldOutRequest(released=True, confirm_freeze=frozen_commit, **over)  # type: ignore[arg-type]


def test_a_correct_freeze_passes_and_returns_the_verified_ids_without_side_effects(
    shared: FrozenRepo,
) -> None:
    fr = shared
    prepared = prepare(fr.paths, request(fr.freeze_commit), config_version=CONFIG.version)
    assert prepared.ids == sorted(IDS)
    assert prepared.info.commit == fr.freeze_commit
    assert prepared.info.head == fr.freeze_commit
    assert not marker_path(fr.paths).exists()  # guards write nothing


def test_refuses_without_released(shared: FrozenRepo) -> None:
    fr = shared
    with pytest.raises(RunRefused, match="--released"):
        prepare(fr.paths, HeldOutRequest(released=False, confirm_freeze=fr.freeze_commit))


@pytest.mark.parametrize("value", [None, "", "   "])
def test_refuses_without_confirm_freeze(shared: FrozenRepo, value: str | None) -> None:
    fr = shared
    with pytest.raises(RunRefused, match="--confirm-freeze"):
        prepare(fr.paths, HeldOutRequest(released=True, confirm_freeze=value))


@pytest.mark.parametrize("bogus", ["not-a-hash", "main", "HEAD", "--help", "zzzzzzz", "12"])
def test_refuses_a_value_that_is_not_a_commit_hash(shared: FrozenRepo, bogus: str) -> None:
    fr = shared
    with pytest.raises(RunRefused, match="commit hash"):
        prepare(fr.paths, request(bogus))


def test_refuses_a_well_formed_hash_that_is_not_in_this_repository(shared: FrozenRepo) -> None:
    fr = shared
    with pytest.raises(RunRefused, match="not a commit in this repository"):
        prepare(fr.paths, request("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"))


def test_refuses_a_commit_that_predates_the_freeze(shared: FrozenRepo) -> None:
    fr = shared
    with pytest.raises(RunRefused, match="does not contain"):
        prepare(fr.paths, request(fr.first_commit))


def test_refuses_when_the_hash_file_changed_after_the_freeze(tmp_path: Path) -> None:
    fr = make_frozen_repo(tmp_path, IDS)
    (fr.paths.splits_dir / "heldout_ids.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(RunRefused, match="differs from the one in commit"):
        prepare(fr.paths, request(fr.freeze_commit))


def test_refuses_when_the_id_list_was_edited_after_the_freeze(tmp_path: Path) -> None:
    fr = make_frozen_repo(tmp_path, IDS)
    ids_file = fr.paths.splits_dir / "heldout_ids.txt"
    ids_file.write_text(ids_file.read_text(encoding="utf-8") + "900000000099\n", encoding="utf-8")
    with pytest.raises(RunRefused, match="does not match heldout_ids.sha256"):
        prepare(fr.paths, request(fr.freeze_commit))


def test_refuses_when_the_committed_id_list_does_not_match_its_committed_hash(
    tmp_path: Path,
) -> None:
    # a "freeze" whose id file was altered before committing: hash and ids disagree in the commit
    fr = make_frozen_repo(tmp_path, IDS)
    ids_file = fr.paths.splits_dir / "heldout_ids.txt"
    ids_file.write_text("1\n2\n", encoding="utf-8")
    git(fr.repo, "add", "-A")
    git(fr.repo, "commit", "-q", "-m", "tamper")
    tampered = git(fr.repo, "rev-parse", "HEAD")
    with pytest.raises(RunRefused, match="committed held-out id list does not match"):
        prepare(fr.paths, request(tampered))


def test_refuses_a_freeze_commit_that_is_not_an_ancestor_of_head(tmp_path: Path) -> None:
    fr = make_frozen_repo(tmp_path, IDS)
    git(fr.repo, "checkout", "-q", fr.first_commit)  # detached HEAD before the freeze
    (fr.repo / "evaluation").mkdir(exist_ok=True)  # that commit has no evaluation/ yet
    with pytest.raises(RunRefused, match="not an ancestor"):
        confirm_freeze(EvalPaths(fr.repo / "evaluation"), fr.freeze_commit)


def test_a_freeze_commit_older_than_head_is_accepted(tmp_path: Path) -> None:
    fr = make_frozen_repo(tmp_path, IDS)
    (fr.repo / "notes.txt").write_text("later work\n", encoding="utf-8")
    git(fr.repo, "add", "-A")
    git(fr.repo, "commit", "-q", "-m", "later")
    prepared = prepare(fr.paths, request(fr.freeze_commit))
    assert prepared.info.commit == fr.freeze_commit
    assert prepared.info.head != fr.freeze_commit


def test_refuses_outside_a_git_repository(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path / "plain" / "evaluation")
    paths.splits_dir.mkdir(parents=True)
    with pytest.raises(RunRefused, match="not inside a git repository"):
        prepare(paths, request("a" * 40))


def test_refuses_a_second_run_when_the_marker_exists_even_a_failed_one(tmp_path: Path) -> None:
    fr = make_frozen_repo(tmp_path, IDS)
    marker = marker_path(fr.paths)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"status": "failed"}\n', encoding="utf-8")
    with pytest.raises(RunRefused, match="runs once"):
        refuse_if_already_run(fr.paths)
    with pytest.raises(RunRefused, match="runs once"):
        prepare(fr.paths, request(fr.freeze_commit))


def test_refuses_a_config_that_is_not_the_expected_one(shared: FrozenRepo) -> None:
    fr = shared
    with pytest.raises(RunRefused, match="--expect-config-version"):
        prepare(
            fr.paths,
            request(fr.freeze_commit, expect_config_version="sha256:ffff"),
            config_version=CONFIG.version,
        )
    prepared = prepare(
        fr.paths,
        request(fr.freeze_commit, expect_config_version=CONFIG.version[:12]),
        config_version=CONFIG.version,
    )
    assert prepared.ids


# ---------------------------------------------------------------------------- through the CLI


def run_args(**over: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "set": "heldout",
        "released": True,
        "contract": "panel",
        "confirm_freeze": None,
        "ablations": False,
        "authorize_bedrock_usd": None,
        "hobson_url": None,
        "expect_config_version": None,
    }
    return argparse.Namespace(**(base | over))


def test_cli_refuses_each_missing_guard_before_it_looks_for_a_decider(
    shared: FrozenRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fr = shared
    monkeypatch.setenv(EVAL_DIR_ENV, str(fr.paths.root))
    monkeypatch.delenv("CSO_DECIDER_URL", raising=False)
    cases = [
        (run_args(released=False, confirm_freeze=fr.freeze_commit), "--released"),
        (run_args(confirm_freeze=None), "--confirm-freeze"),
        (run_args(confirm_freeze="bogus"), "commit hash"),
        (run_args(confirm_freeze=fr.first_commit), "does not contain"),
        (run_args(confirm_freeze=fr.freeze_commit, contract="permutation"), "fact-panel contract"),
    ]
    for args, expected in cases:
        assert eval_cli._cmd_run(args) == 1
        assert expected in capsys.readouterr().err
    assert not marker_path(fr.paths).exists()


def test_cli_checks_the_guards_before_the_decider_url(
    shared: FrozenRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fr = shared
    monkeypatch.setenv(EVAL_DIR_ENV, str(fr.paths.root))
    monkeypatch.delenv("CSO_DECIDER_URL", raising=False)
    assert eval_cli._cmd_run(run_args(confirm_freeze=fr.freeze_commit)) == 1
    assert "CSO_DECIDER_URL" in capsys.readouterr().err  # guards passed, then the preflight
    assert not marker_path(fr.paths).exists()  # a missing Decider never burns the one run


# ---------------------------------------------------------------------------- no tuning hooks


def test_the_run_has_no_tuning_parameters() -> None:
    names = set(inspect.signature(heldout.run_all).parameters) | set(
        inspect.signature(heldout.execute_heldout).parameters
    )
    forbidden = {"profile", "thresholds", "threshold", "low", "high", "config_path", "tune", "k"}
    assert not (names & forbidden)
    fields = set(inspect.signature(HeldOutRequest).parameters)
    assert fields == {
        "released",
        "confirm_freeze",
        "ablations",
        "authorize_bedrock_usd",
        "hobson_url",
        "expect_config_version",
    }
    assert heldout.PROFILE == "compact"

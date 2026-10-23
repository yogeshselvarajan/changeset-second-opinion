"""`cso eval panel-diagnostic` must not send held-out ids through the Decider by accident."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from cso.evaluation import eval_cli
from cso.evaluation.eval_cli import HELDOUT_DIAGNOSTIC_NOTE, diagnostic_heldout_problem
from cso.evaluation.paths import EVAL_DIR_ENV
from cso.evaluation.split import SHA_FILE


def test_heldout_needs_the_explicit_flag_even_before_the_freeze() -> None:
    assert diagnostic_heldout_problem("heldout", False, frozen=False) is not None
    assert diagnostic_heldout_problem("heldout", False, frozen=True) is not None
    assert diagnostic_heldout_problem("heldout", True, frozen=True) is None


def test_all_needs_the_flag_only_once_the_split_is_frozen() -> None:
    assert diagnostic_heldout_problem("all", False, frozen=True) is not None
    assert diagnostic_heldout_problem("all", False, frozen=False) is None
    assert diagnostic_heldout_problem("all", True, frozen=True) is None


def test_dev_never_needs_the_flag() -> None:
    assert diagnostic_heldout_problem("dev", False, frozen=True) is None


def test_the_note_states_exactly_what_happened() -> None:
    assert "no longer unseen" in HELDOUT_DIAGNOSTIC_NOTE
    assert "read no labels" in HELDOUT_DIAGNOSTIC_NOTE


@pytest.mark.parametrize("set_name", ["heldout", "all"])
def test_the_command_refuses_before_any_network_or_settings_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    set_name: str,
) -> None:
    splits = tmp_path / "splits"
    splits.mkdir()
    (splits / SHA_FILE).write_text("0" * 64 + "\n", encoding="utf-8")
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the guard must run first")

    monkeypatch.setattr(eval_cli, "get_settings", boom)
    args = argparse.Namespace(set=set_name, profile="compact", tag="", include_heldout=False)
    assert eval_cli._cmd_panel_diagnostic(args) == 1
    assert "--include-heldout" in capsys.readouterr().err

"""The real `cso eval run --set heldout` path end to end.

Covers the guards, the preflight, the one run, the refused second run and the combined report,
over a temporary git repository (nothing leaves the machine).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from heldout_support import GOOD_UA, all_snapshots, decider, make_frozen_repo, provider

from cso.evaluation import eval_cli
from cso.evaluation.heldout import marker_path
from cso.evaluation.heldout_report import NO_GOLD
from cso.evaluation.paths import EVAL_DIR_ENV
from cso.settings import Settings

IDS = [
    900000000001,
    900000000002,
    900000000003,
    900000000004,
    900000000005,
    900000000006,
    900000000007,
    900000000008,
]


def run_args(commit: str, **over: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "set": "heldout",
        "released": True,
        "contract": "panel",
        "confirm_freeze": commit,
        "ablations": False,
        "authorize_bedrock_usd": None,
        "hobson_url": None,
        "expect_config_version": None,
    }
    return argparse.Namespace(**(base | over))


async def call(fn: Any, args: argparse.Namespace) -> int:
    """Run a sync CLI command in a worker thread (it starts its own event loop)."""
    return await anyio.to_thread.run_sync(fn, args)


async def test_the_full_cli_path_refuses_a_dead_decider_then_runs_once_then_refuses_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fr = make_frozen_repo(tmp_path, IDS)
    snaps = await all_snapshots()
    monkeypatch.setenv(EVAL_DIR_ENV, str(fr.paths.root))
    monkeypatch.setattr(
        eval_cli,
        "get_settings",
        lambda: Settings(decider_url="http://decider.test", user_agent=GOOD_UA),
    )
    monkeypatch.setattr(eval_cli, "_cached_snapshots", lambda _paths: provider(snaps))

    # 1. the Decider is down: the preflight fails and the one run is NOT consumed
    monkeypatch.setattr(
        eval_cli.DeciderClient,
        "from_settings",
        classmethod(lambda cls, settings, **kw: decider(health_status=503)),
    )
    assert await call(eval_cli._cmd_run, run_args(fr.freeze_commit)) == 1
    assert capsys.readouterr().err.strip()
    assert not marker_path(fr.paths).exists()

    # 2. the Decider is up: the run happens, with the Haiku baselines reported as not run
    monkeypatch.setattr(
        eval_cli.DeciderClient,
        "from_settings",
        classmethod(lambda cls, settings, **kw: decider()),
    )
    rc = await call(eval_cli._cmd_run, run_args(fr.freeze_commit, authorize_bedrock_usd=5.0))
    assert rc == 0
    marker = json.loads(marker_path(fr.paths).read_text(encoding="utf-8"))
    assert marker["status"] == "finished" and marker["freeze_commit"] == fr.freeze_commit
    assert marker["bedrock_authorised_usd"] == 5.0
    (md,) = fr.paths.results_dir.glob("*-heldout-*.md")
    text = md.read_text(encoding="utf-8")
    assert NO_GOLD in text
    assert "haiku_decision" in text and "the application is not in live mode" in text
    assert fr.freeze_commit[:8] in md.name

    # 3. a second attempt is refused, whatever its flags
    capsys.readouterr()
    assert await call(eval_cli._cmd_run, run_args(fr.freeze_commit, ablations=True)) == 1
    assert "runs once" in capsys.readouterr().err

    # 4. the combined report renders from the files that now exist, running nothing
    out = tmp_path / "combined.md"
    assert eval_cli._cmd_report(argparse.Namespace(latest=True, out=str(out))) == 0
    combined = out.read_text(encoding="utf-8")
    assert "# Combined evaluation report" in combined
    assert "Freeze commit" in combined and NO_GOLD in combined
    assert "No spike results file exists yet." in combined


def test_report_prints_to_stdout_when_no_out_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path / "evaluation"))
    assert eval_cli._cmd_report(argparse.Namespace(latest=True, out=None)) == 0
    printed = capsysbinary.readouterr().out.decode("utf-8")
    assert printed.startswith("# Combined evaluation report")
    assert "The held-out evaluation has not been run yet." in printed


def test_report_requires_the_latest_flag() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    eval_cli.add_eval_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["eval", "report"])
    args = parser.parse_args(["eval", "report", "--latest"])
    assert args.latest is True and args.func is eval_cli._cmd_report


def test_the_run_parser_exposes_the_guard_flags_and_no_tuning_flags() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    eval_cli.add_eval_parser(sub)
    args = parser.parse_args(
        [
            "eval",
            "run",
            "--set",
            "heldout",
            "--released",
            "--confirm-freeze",
            "abc1234",
            "--ablations",
            "--authorize-bedrock-usd",
            "2.5",
            "--hobson-url",
            "http://127.0.0.1:8100",
            "--expect-config-version",
            "sha256:01ae",
        ]
    )
    assert (args.confirm_freeze, args.ablations, args.authorize_bedrock_usd) == (
        "abc1234",
        True,
        2.5,
    )
    assert (args.hobson_url, args.expect_config_version) == ("http://127.0.0.1:8100", "sha256:01ae")
    for tuning in ("--profile", "--threshold", "--low", "--high", "--config"):
        with pytest.raises(SystemExit):
            parser.parse_args(["eval", "run", "--set", "heldout", tuning, "x"])

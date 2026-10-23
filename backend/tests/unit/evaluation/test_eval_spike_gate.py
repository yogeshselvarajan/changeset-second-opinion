from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cso.evaluation.eval_cli import _cmd_spike
from cso.evaluation.labels import GoldLabel
from cso.evaluation.paths import EVAL_DIR_ENV, EvalPaths
from cso.evaluation.report import render_not_run, render_spike
from cso.evaluation.runner import ItemRun
from cso.evaluation.spike import (
    REQUIRED_LABELS,
    evaluate_gate,
    not_run_line,
    summarise,
    verdict_line,
)
from cso.evaluation.split import Split, write_frozen

CLASSES = [
    "consistent_edit",
    "likely_good_faith_mistake",
    "possible_deliberate_damage",
    "needs_local_knowledge",
]


def _gold(cs: int, nature: str, response: str = "no_action_suggested") -> GoldLabel:
    return GoldLabel("dev", cs, nature, response, "agree", None, "2026-10-18")


def _run(
    cs: int, *, rules: str, k3: str, p: float, k1: str | None = None, err: str | None = None
) -> ItemRun:
    return ItemRun(
        changeset_id=cs,
        rules_nature=rules,
        rules_response="no_action_suggested",
        rules_fired=(),
        k1_nature=None if err else (k1 or k3),
        k1_response=None if err else "no_action_suggested",
        k3_nature=None if err else k3,
        k3_response=None if err else "no_action_suggested",
        max_p_nature=None if err else p,
        order_sensitivity=None if err else 0.1,
        latency_ms=None if err else 900,
        server_latency_ms=None if err else 440.0,
        error=err,
    )


def _dataset(
    decider_correct: int, rules_correct: int, n: int = 30
) -> tuple[list[ItemRun], dict[int, GoldLabel]]:
    gold: dict[int, GoldLabel] = {}
    runs: list[ItemRun] = []
    for i in range(n):
        truth = CLASSES[i % 4]
        gold[i] = _gold(i, truth)
        wrong = CLASSES[(i + 1) % 4]
        runs.append(
            _run(
                i,
                rules=truth if i < rules_correct else wrong,
                k3=truth if i < decider_correct else wrong,
                p=0.9 - i * 0.01,
            )
        )
    return runs, gold


def test_gate_is_go_when_both_conditions_hold() -> None:
    runs, gold = _dataset(decider_correct=30, rules_correct=10)
    gate = evaluate_gate(summarise(runs, gold, order_sensitivity_cap=0.3))
    assert gate.f1_condition and gate.top_third_condition
    assert verdict_line(gate) == "VERDICT: GO"


def test_gate_is_no_go_when_neither_holds() -> None:
    # Rules are mostly right; the Decider is wrong exactly where it is most confident.
    gold: dict[int, GoldLabel] = {}
    runs: list[ItemRun] = []
    for i in range(30):
        truth = CLASSES[i % 4]
        gold[i] = _gold(i, truth)
        k3 = truth if i >= 20 else CLASSES[(i + 1) % 4]
        rules = truth if i < 25 else CLASSES[(i + 2) % 4]
        runs.append(_run(i, rules=rules, k3=k3, p=0.95 - i * 0.01))
    gate = evaluate_gate(summarise(runs, gold, order_sensitivity_cap=0.3))
    assert not gate.f1_condition and not gate.top_third_condition
    assert verdict_line(gate) == "VERDICT: NO-GO"


def test_gate_is_borderline_when_one_condition_holds() -> None:
    # The Decider beats the rules by a wide margin (F1 condition), but its ten most confident
    # items are all wrong, so the top-third accuracy bound fails.
    gold: dict[int, GoldLabel] = {}
    runs: list[ItemRun] = []
    for i in range(30):
        truth = CLASSES[i % 4]
        gold[i] = _gold(i, truth)
        k3 = CLASSES[(i + 1) % 4] if i < 10 else truth
        runs.append(_run(i, rules=CLASSES[(i + 2) % 4], k3=k3, p=0.95 - i * 0.01))
    gate = evaluate_gate(summarise(runs, gold, order_sensitivity_cap=0.3))
    assert gate.f1_condition and not gate.top_third_condition
    assert "BORDERLINE" in verdict_line(gate)


def test_ambiguous_items_are_excluded_from_accuracy_and_counted_as_a_rate() -> None:
    runs, gold = _dataset(decider_correct=30, rules_correct=30, n=12)
    gold[0] = _gold(0, "ambiguous")
    gold[1] = _gold(1, "ambiguous")
    summary = summarise(runs, gold, order_sensitivity_cap=0.3)
    assert (summary.n_labelled, summary.n_scored) == (12, 10)
    assert (summary.ambiguous.k, summary.ambiguous.n) == (2, 12)


def test_decider_failures_are_counted_and_never_scored_as_answers() -> None:
    runs, gold = _dataset(decider_correct=30, rules_correct=30, n=8)
    runs[0] = _run(0, rules="consistent_edit", k3="", p=0, err="DeciderTimeout: slow")
    summary = summarise(runs, gold, order_sensitivity_cap=0.3)
    assert summary.n_decider_failures == 1
    assert summary.n_scored == 7


def test_every_reported_proportion_has_a_wilson_interval_in_the_report() -> None:
    runs, gold = _dataset(decider_correct=30, rules_correct=10)
    summary = summarise(runs, gold, order_sensitivity_cap=0.3)
    text = render_spike(
        summary, evaluate_gate(summary), date="2026-10-18", config_version="v", model="m"
    )
    assert "VERDICT: GO" in text
    assert text.count("[") >= 10  # intervals appear as [lo, hi]
    assert "never reported as validation" in text


def test_not_run_text_has_no_verdict() -> None:
    assert not_run_line(12) == f"NOT RUN: insufficient labels (12/{REQUIRED_LABELS})"
    text = render_not_run(12, date="2026-10-18")
    assert "NOT RUN: insufficient labels (12/60)" in text
    for word in ("VERDICT", "NO-GO", "BORDERLINE"):
        assert word not in text


def _frozen_dir(tmp_path: Path) -> EvalPaths:
    paths = EvalPaths(tmp_path)
    write_frozen(paths, Split(tuple(range(1, 61)), (1001, 1002), ()))
    return paths


def test_spike_command_writes_not_run_and_no_verdict_with_too_few_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _frozen_dir(tmp_path)
    labels = paths.adjudicated("dev")
    labels.parent.mkdir(parents=True)
    labels.write_text(
        "".join(json.dumps(_gold(i, "consistent_edit").to_json()) + "\n" for i in range(1, 13)),
        encoding="utf-8",
    )
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    monkeypatch.delenv("CSO_DECIDER_URL", raising=False)
    # version 1 labels belong to the permutation contract
    assert _cmd_spike(argparse.Namespace(contract="permutation")) == 0
    out = capsys.readouterr().out
    assert "NOT RUN: insufficient labels (12/60)" in out
    reports = list(paths.results_dir.glob("spike-*.md"))
    assert len(reports) == 1
    body = reports[0].read_text(encoding="utf-8")
    assert "NOT RUN: insufficient labels (12/60)" in body and "VERDICT" not in body


def test_spike_command_never_overwrites_a_real_report_with_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cso.evaluation.eval_cli import _today

    paths = _frozen_dir(tmp_path)
    paths.results_dir.mkdir(parents=True)
    real = paths.results_dir / f"spike-{_today()}.md"
    real.write_text("# real\n\nVERDICT: GO\n", encoding="utf-8")
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    assert _cmd_spike(argparse.Namespace(contract="panel")) == 0
    assert real.read_text(encoding="utf-8") == "# real\n\nVERDICT: GO\n"


def test_smoke_report_is_marked_synthetic_and_never_claims_hand_labels() -> None:
    from cso.evaluation.report import SMOKE_BANNER, render_run

    runs, gold = _dataset(decider_correct=30, rules_correct=10, n=8)
    summary = summarise(runs, gold, order_sensitivity_cap=0.3)
    smoke = render_run(
        summary,
        title="Pipeline smoke test",
        banner=SMOKE_BANNER,
        date="d",
        config_version="v",
        model="m",
    )
    assert "PIPELINE SMOKE TEST - SYNTHETIC - NOT A VERDICT" in smoke
    assert "synthetic hints" in smoke and "hand labels by the authors" not in smoke
    assert "VERDICT:" not in smoke
    real = render_run(summary, title="Run", banner=None, date="d", config_version="v", model="m")
    assert "hand labels by the authors" in real and "VERDICT:" not in real


def test_spike_without_a_split_is_not_run_zero_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    assert _cmd_spike(argparse.Namespace(contract="panel")) == 0
    assert "NOT RUN: insufficient labels (0/60)" in capsys.readouterr().out

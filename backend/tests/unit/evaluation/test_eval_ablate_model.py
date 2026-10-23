"""The model-size ablation report, chart, saved-run loader and argument guards."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from defusedxml import ElementTree as ET  # noqa: N817

from cso.domain.panel import PANEL_NOUL_IDS
from cso.evaluation import eval_cli
from cso.evaluation.ablate_model import (
    ModelRun,
    compare_models,
    render_ablation,
    render_chart,
    runs_from_json,
)
from cso.evaluation.eval_cli import ablation_problem
from cso.evaluation.labels import LABELLED_PROBES, GoldLabel
from cso.evaluation.panel_eval import PanelItemRun
from cso.evaluation.paths import EVAL_DIR_ENV
from cso.settings import get_settings


def gold(cs: int, nature: str = "deliberate_harm", answer: str = "yes") -> GoldLabel:
    return GoldLabel(
        "dev",
        cs,
        nature,
        "none",
        "agree",
        None,
        "2026-10-19",
        version=2,
        probes=dict.fromkeys(LABELLED_PROBES, answer),
    )


def run(
    cs: int, state: str, nature: str = "deliberate_harm", error: str | None = None
) -> PanelItemRun:
    if error:
        return PanelItemRun(cs, "benign", "none", (), error=error)
    return PanelItemRun(
        changeset_id=cs,
        rules_nature="benign",
        rules_response="none",
        rules_fired=("R2",),
        probabilities=dict.fromkeys(PANEL_NOUL_IDS, 0.9),
        states=dict.fromkeys(PANEL_NOUL_IDS, state),
        composed_nature=nature,
        composed_response="question",
        composed_lane="review",
        composed_band="medium",
        advisory_choice=nature,
        advisory_confidence=0.7,
        input_tokens=1200,
        latency_ms=900 + cs,
        server_latency_ms=800.0,
    )


def model(label: str, name: str, runs: list[PanelItemRun]) -> ModelRun:
    return ModelRun(label, name, tuple(runs))


def test_the_report_lines_two_models_up_on_the_same_items() -> None:
    ids = range(1, 31)
    labels = {i: gold(i) for i in ids}
    small = model("2B", "decider-2b (cuda)", [run(i, "yes" if i % 2 else "no") for i in ids])
    big = model("E4B", "decider-e4b (cuda)", [run(i, "yes") for i in ids])
    result = compare_models(small, big, labels)
    text = render_ablation(
        result,
        date="2026-10-19",
        config_version="abc123",
        provenance="LABELS: AI-ONLY. Every gold label was produced by an AI (Claude).",
        chart_name="chart.svg",
    )
    assert "# Model-size ablation: 2B vs E4B (2026-10-19)" in text
    assert "ABLATION - NOT A RELEASE GATE" in text
    assert "LABELS: AI-ONLY" in text  # the banner travels with the numbers
    assert "`decider-2b (cuda)`" in text and "`decider-e4b (cuda)`" in text
    assert "Items in both runs (dev set): 30; both answered: 30" in text
    assert "![Per-probe accuracy, 2B vs E4B](chart.svg)" in text
    for probe in LABELLED_PROBES:
        assert f"| {probe} |" in text
    assert result.labelled and result.summary_b.pooled_decided.k == 30 * len(LABELLED_PROBES)
    assert result.summary_a.pooled_decided.k == 15 * len(LABELLED_PROBES)
    assert "intervals apart" in text  # 0.50 against 1.00 on 30 items is not noise


def test_only_items_both_servers_answered_for_are_compared() -> None:
    labels = {i: gold(i) for i in range(1, 6)}
    a = model("2B", "a", [run(i, "yes") for i in range(1, 6)])
    b = model("E4B", "b", [run(i, "yes") for i in range(1, 4)] + [run(4, "yes", error="Timeout")])
    result = compare_models(a, b, labels)
    assert result.n_items == 4  # item 5 is missing from b; item 4 is there but failed
    assert result.n_both_answered == 3
    assert "| E4B | " in render_ablation(result, date="d", config_version="v", provenance="p")
    assert result.nature_agreement.k == 3 and result.nature_agreement.n == 3


def test_without_labels_the_report_says_so_and_still_compares_unknown_rates() -> None:
    a = model("2B", "a", [run(i, "unknown") for i in range(1, 6)])
    b = model("E4B", "b", [run(i, "yes") for i in range(1, 6)])
    result = compare_models(a, b, {})
    text = render_ablation(result, date="d", config_version="v", provenance="LABELS: NONE.")
    assert not result.labelled
    assert "No adjudicated probe labels cover these items" in text
    assert "n/a (n=0)" in text


def test_a_model_that_was_not_asked_is_a_visible_gap_not_a_zero() -> None:
    a = model("2B", "a", [run(1, "yes")])
    b = model("12B", "b", [])
    result = compare_models(a, b, {1: gold(1)})
    assert result.n_items == 0
    text = render_ablation(result, date="d", config_version="v", provenance="p")
    assert "Items in both runs (dev set): 0" in text


def test_the_chart_is_valid_svg_with_both_models_and_whiskers() -> None:
    labels = {i: gold(i) for i in range(1, 31)}
    result = compare_models(
        model("2B", "a", [run(i, "yes" if i % 3 else "no") for i in range(1, 31)]),
        model("E4B", "b", [run(i, "yes") for i in range(1, 31)]),
        labels,
    )
    svg = render_chart(result)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and root.attrib["role"] == "img"
    assert "Wilson 95 percent" in root.attrib["aria-label"]
    assert svg.count("<line") > len(LABELLED_PROBES) * 3  # gridlines plus whiskers
    for probe in LABELLED_PROBES:
        assert probe in svg
    assert "—" not in svg and "–" not in svg


def test_the_chart_marks_probes_without_labels_instead_of_drawing_zero() -> None:
    result = compare_models(
        model("2B", "a", [run(1, "yes")]), model("E4B", "b", [run(1, "yes")]), {}
    )
    svg = render_chart(result)
    ET.fromstring(svg)
    assert "no labels" in svg


def test_labels_with_special_characters_cannot_break_the_chart() -> None:
    result = compare_models(
        model("<b>2B</b>", "a", [run(1, "yes")]), model("E&4B", "b", [run(1, "yes")]), {}
    )
    ET.fromstring(render_chart(result))


def test_a_saved_run_loads_back_into_the_same_items() -> None:
    original = [run(1, "yes"), run(2, "no"), run(3, "yes", error="DeciderTimeout: x")]
    payload = json.dumps(
        {
            "model": "decider-2b (cuda)",
            "config_version": "abc",
            "items": [asdict(r) for r in original],
        }
    )
    model_name, version, loaded = runs_from_json(payload)
    assert (model_name, version) == ("decider-2b (cuda)", "abc")
    assert loaded == original  # tuples and dicts come back as tuples and dicts


def test_extra_keys_in_a_saved_run_are_ignored() -> None:
    item = asdict(run(1, "yes")) | {"added_later": 1}
    _m, _v, loaded = runs_from_json(json.dumps({"items": [item]}))
    assert loaded[0].changeset_id == 1


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8100", "http://localhost:8100", "http://[::1]:8100"]
)
def test_a_loopback_server_is_accepted(url: str) -> None:
    assert ablation_problem("E4B", url) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8100",
        "http://example.org:8100",
        "https://api.openstreetmap.org",
        "ftp://127.0.0.1/x",
        "127.0.0.1:8100",
        "",
    ],
)
def test_a_server_that_is_not_on_this_machine_is_refused(url: str) -> None:
    problem = ablation_problem("E4B", url)
    assert problem is not None and "this machine" in problem


@pytest.mark.parametrize("label", ["", "a b", "../x", "x/y", "a" * 41, "e4b;rm", "e4b\n"])
def test_a_label_that_could_escape_the_results_folder_is_refused(label: str) -> None:
    assert ablation_problem(label, "http://127.0.0.1:8100") is not None


def _args(**over: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "set": "dev",
        "decider_url": "http://127.0.0.1:8100",
        "label": "E4B",
        "baseline_label": "2B",
        "baseline_json": None,
    }
    return argparse.Namespace(**(base | over))


def test_the_command_writes_the_report_chart_and_run_without_a_baseline_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "splits").mkdir()
    (tmp_path / "splits" / "dev_ids.txt").write_text("1\n2\n3\n", encoding="utf-8")
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    monkeypatch.setenv("CSO_USER_AGENT", "Test/1 (+https://example.org/repo; test@example.org)")
    get_settings.cache_clear()
    base = tmp_path / "base.json"
    base.write_text(
        json.dumps(
            {
                "model": "decider-2b (cuda)",
                "config_version": "v",
                "items": [asdict(run(i, "yes")) for i in (1, 2, 3)],
            }
        ),
        encoding="utf-8",
    )
    asked: list[str] = []

    async def fake_runs(**kwargs: object) -> tuple[list[PanelItemRun], str]:
        asked.append(str(kwargs["url"]))
        return [run(i, "no") for i in (1, 2, 3)], "decider-e4b (cuda)"

    monkeypatch.setattr(eval_cli, "_ablation_runs", fake_runs)
    code = eval_cli._cmd_ablate_model(_args(baseline_json=str(base)))
    assert code == 0 and asked == ["http://127.0.0.1:8100"]
    out = tmp_path / "results"
    names = sorted(p.name for p in out.glob("ablation-model-E4B-*"))
    assert [n.rsplit(".", 1)[1] for n in names] == ["json", "md", "svg"]
    report = next(out.glob("ablation-model-E4B-*.md")).read_text(encoding="utf-8")
    assert "2B vs E4B" in report and "LABELS: NONE" in report
    assert "wrote" in capsys.readouterr().out


def test_the_command_refuses_a_remote_server_before_touching_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the guard must run first")

    monkeypatch.setattr(eval_cli, "get_settings", boom)
    assert eval_cli._cmd_ablate_model(_args(decider_url="http://10.1.2.3:8100")) == 1
    assert "this machine" in capsys.readouterr().err


@pytest.mark.parametrize("label", ["E4B", "gemma-4-12B", "v1.2_test"])
def test_ordinary_labels_are_accepted(label: str) -> None:
    assert ablation_problem(label, "http://127.0.0.1:8100") is None

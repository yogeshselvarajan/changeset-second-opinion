"""`cso eval report --latest`: rendered from stored files only, with a verdict only when gold labels
exist, and never a GO for a run whose gold labels are missing."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from heldout_support import CONFIG, run_it

from cso.domain.panel import PANEL_NOUL_IDS
from cso.evaluation.combined_report import latest_file, render_combined, runs_from_json
from cso.evaluation.labels import LABELLED_PROBES, NOT_COLLECTED, GoldLabel, LabelStore, write_gold
from cso.evaluation.panel_eval import PanelItemRun
from cso.evaluation.paths import EvalPaths
from cso.evaluation.split import Split, write_frozen

DEV_IDS = tuple(range(1, 61))


def panel_run(cs: int) -> PanelItemRun:
    return PanelItemRun(
        changeset_id=cs,
        rules_nature="consistent_edit",
        rules_response="no_action_suggested",
        rules_fired=(),
        probabilities=dict.fromkeys(PANEL_NOUL_IDS, 0.1),
        states=dict.fromkeys(PANEL_NOUL_IDS, "no"),
        composed_nature="consistent_edit",
        composed_response="no_action_suggested",
        composed_lane="looks_consistent",
        composed_band="confident",
        nature_row="N4",
        response_row="P5",
        advisory_choice="consistent_edit",
        advisory_confidence=0.3,
        input_tokens=1500,
        latency_ms=1100,
        server_latency_ms=600.0,
    )


def write_results(paths: EvalPaths, name: str, n: int = 60) -> None:
    payload = {
        "date": "2026-10-17",
        "set": "dev",
        "config_version": CONFIG.version,
        "model": "strands-decider (cuda)",
        "profile": "compact",
        "items": [asdict(panel_run(i)) for i in range(1, n + 1)],
    }
    path = paths.results_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_dev_gold(
    paths: EvalPaths, n: int, labeller: str, *, extra_labeller: str | None = None
) -> None:
    write_frozen(paths, Split(DEV_IDS, (1001,), ()))
    gold = [
        GoldLabel(
            "dev",
            i,
            "consistent_edit",
            NOT_COLLECTED,
            "adjudicated",
            labeller,
            "t",
            version=2,
            probes=dict.fromkeys(LABELLED_PROBES, "no"),
        )
        for i in range(1, n + 1)
    ]
    write_gold(paths.adjudicated("dev"), gold)
    store = LabelStore(paths.labels("dev"), "dev")
    for who in filter(None, [labeller, extra_labeller]):
        store.append(
            changeset_id=1,
            labeller=who,
            session="s1",
            nature="consistent_edit",
            probes=dict.fromkeys(LABELLED_PROBES, "no"),
        )


# ----------------------------------------------------------------------------- file choice


def test_latest_file_prefers_the_newest_date_and_a_tagged_rerun_over_the_plain_one(
    tmp_path: Path,
) -> None:
    for name in (
        "panel-diagnostic-2026-10-17.json",
        "panel-diagnostic-2026-10-17-v2.json",
        "panel-diagnostic-2026-10-16-v3.json",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert latest_file(tmp_path, "panel-diagnostic-*.json") == (
        tmp_path / "panel-diagnostic-2026-10-17-v2.json"
    )
    (tmp_path / "panel-diagnostic-2026-10-18.json").write_text("{}", encoding="utf-8")
    assert (
        latest_file(tmp_path, "panel-diagnostic-*.json").name == "panel-diagnostic-2026-10-18.json"
    )
    assert latest_file(tmp_path, "nothing-*.json") is None


def test_the_held_out_marker_is_not_mistaken_for_a_results_file(tmp_path: Path) -> None:
    (tmp_path / "heldout-run.json").write_text("{}", encoding="utf-8")
    assert latest_file(tmp_path, "*-heldout-*.json") is None


def test_older_files_without_newer_fields_still_load() -> None:
    old = asdict(panel_run(1))
    for field in ("norules_nature", "norules_response", "norules_lane"):
        old.pop(field)
    old["unknown_future_field"] = 1
    (run,) = runs_from_json([old])
    assert run.norules_nature is None and run.rules_fired == ()


# ---------------------------------------------------------------------------- the sections


def test_with_no_results_each_section_says_so_and_nothing_claims_a_verdict(tmp_path: Path) -> None:
    text = render_combined(EvalPaths(tmp_path / "evaluation"), CONFIG)
    assert "No spike results file exists yet." in text
    assert "No panel diagnostic file exists yet." in text
    assert "The held-out evaluation has not been run yet." in text
    assert "Nothing was run to produce it" in text
    assert "VERDICT" not in text and not re.search(r"\bGO\b", text)


def test_a_spike_file_without_enough_gold_is_not_run_and_never_shows_go(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path / "evaluation")
    write_results(paths, "spike-2026-10-17.json")
    write_dev_gold(paths, 59, "claude")  # one label short of the 60 required
    text = render_combined(paths, CONFIG)
    assert "NOT RUN: insufficient labels (59/60)" in text
    assert "no verdict is shown" in text
    assert "VERDICT" not in text and not re.search(r"\bGO\b|NO-GO|BORDERLINE", text)


def test_a_spike_file_with_no_gold_at_all_is_not_run(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path / "evaluation")
    write_results(paths, "spike-2026-10-17.json")
    text = render_combined(paths, CONFIG)
    assert "NOT RUN: insufficient labels (0/60)" in text
    assert "VERDICT" not in text and not re.search(r"\bGO\b", text)


def test_with_gold_the_spike_section_is_recomputed_and_carries_the_ai_only_banner(
    tmp_path: Path,
) -> None:
    paths = EvalPaths(tmp_path / "evaluation")
    write_results(paths, "spike-2026-10-17.json")
    write_dev_gold(paths, 60, "claude")
    text = render_combined(paths, CONFIG)
    verdict = next(line for line in text.splitlines() if line.startswith("VERDICT:"))
    assert "AI-ONLY LABELS" in verdict
    assert "LABELS: AI-ONLY" in text


def test_a_person_among_the_dev_labellers_makes_the_spike_banner_mixed(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path / "evaluation")
    write_results(paths, "spike-2026-10-17.json")
    write_dev_gold(paths, 60, "claude", extra_labeller="Yogesh")
    text = render_combined(paths, CONFIG)
    assert "LABELS: MIXED" in text and "Yogesh" in text
    assert "AI-ONLY LABELS" not in next(
        line for line in text.splitlines() if line.startswith("VERDICT:")
    )


def test_a_non_panel_spike_file_is_not_rendered(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path / "evaluation")
    paths.results_dir.mkdir(parents=True)
    (paths.results_dir / "spike-2026-10-17.json").write_text(
        json.dumps({"items": [{"changeset_id": 1, "k1_nature": "x"}]}), encoding="utf-8"
    )
    assert "is not a fact-panel spike file" in render_combined(paths, CONFIG)


def test_the_diagnostic_section_is_rendered_label_free_from_the_stored_runs(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path / "evaluation")
    write_results(paths, "panel-diagnostic-2026-10-17.json", n=5)
    text = render_combined(paths, CONFIG)
    assert "NOT A VERDICT" in text
    assert "panel-diagnostic-2026-10-17.json" in text
    assert "VERDICT:" not in text


async def test_the_held_out_section_is_re_rendered_from_its_results_file(tmp_path: Path) -> None:
    paths, payload = await run_it(tmp_path)
    text = render_combined(paths, CONFIG)
    assert "Held-out evaluation (2026-10-20)" in text
    assert payload["freeze_commit"] in text
    assert "no gold labels: only label-free statistics" in text
    assert "VERDICT" not in text and not re.search(r"\bGO\b", text)
    assert "## Held-out evaluation" in text and "### Systems and ablations attempted" in text

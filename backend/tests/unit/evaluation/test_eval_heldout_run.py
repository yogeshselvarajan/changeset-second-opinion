"""A full held-out run with fakes: marker lifecycle, listed-but-not-run systems, label-free versus
scored output, the rules on/off safety demonstration, Haiku with a ceiling, and ablations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from heldout_support import (
    CONFIG,
    DATE,
    FAKE_COMMIT,
    all_snapshots,
    decider,
    fake_haiku,
    gold_for,
    haiku_reply,
    provider,
    run_it,
)

from cso.domain.panel import PANEL_INSTRUCTIONS
from cso.evaluation.ablation_text import INSTRUCTION_VARIANTS, PARAPHRASE_NAMES, WITHOUT_CUES
from cso.evaluation.haiku_baseline import estimate_usd
from cso.evaluation.heldout import RunRefused, marker_path, refuse_if_already_run
from cso.evaluation.heldout_report import NO_GOLD, render_heldout

STEM = f"{DATE}-heldout-{FAKE_COMMIT[:8]}"
INTERVAL = re.compile(r"\d+/\d+ = \d\.\d\d(?! \[\d)")  # a proportion with no interval after it
PERCENT = re.compile(r"(?!95%)\d+(?:\.\d+)?%")  # any percentage except Wilson 95%
FIXTURE = {
    "03": 900000000003,
    "04": 900000000004,
    "06": 900000000006,
}  # fixtures where a parsed rule fires (R3, R1+R3, R3)


def by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in rows}


# ---------------------------------------------------------------------- label-free default run


async def test_a_label_free_run_writes_results_and_a_finished_marker(tmp_path: Path) -> None:
    paths, payload = await run_it(tmp_path)
    assert (paths.results_dir / f"{STEM}.json").exists()
    assert (paths.results_dir / f"{STEM}.md").exists()
    marker = json.loads(marker_path(paths).read_text(encoding="utf-8"))
    assert marker["status"] == "finished" and marker["freeze_commit"] == FAKE_COMMIT
    assert marker["config_version"] == CONFIG.version
    assert {"rule_baseline_v1", "decider_panel_composed"} <= set(marker["systems_requested"])
    assert payload["labels"]["mode"] == "label_free" and payload["n_items"] == 8
    receipts = paths.results_dir / "receipts" / STEM / "product"
    assert len(list(receipts.glob("*.json"))) == 8
    receipt = json.loads(receipts.joinpath("900000000001.json").read_text(encoding="utf-8"))
    assert not {"evidence", "rendered_text", "state", "comment"} & set(receipt)  # numbers only


async def test_without_gold_the_report_says_so_and_prints_no_accuracy_or_verdict(
    tmp_path: Path,
) -> None:
    paths, _ = await run_it(tmp_path)
    text = (paths.results_dir / f"{STEM}.md").read_text(encoding="utf-8")
    assert NO_GOLD in text
    lowered = text.lower()
    for word in ("accuracy", "macro-f1", "verdict", "precision", "recall"):
        assert word not in lowered
    assert not re.search(r"\bGO\b", text) and "NO-GO" not in text
    assert not INTERVAL.search(text) and not PERCENT.search(text)


async def test_systems_that_cannot_run_are_listed_with_their_reasons(tmp_path: Path) -> None:
    paths, payload = await run_it(tmp_path)
    systems, ablations = by_name(payload["systems"]), by_name(payload["ablations"])
    assert systems["rule_baseline_v1"]["status"] == "ran"
    assert systems["decider_panel_composed"]["n_answered"] == 8
    assert systems["decider_permutation_k3"]["status"] == "not run"
    assert "ADR-009" in systems["decider_permutation_k3"]["reason"]
    assert systems["haiku_decision"]["status"] == "not run"
    assert systems["haiku_decision"]["reason"] == "not requested"
    assert systems["haiku_plus_rules"]["status"] == "not run"
    for name in (WITHOUT_CUES, *PARAPHRASE_NAMES):
        assert ablations[name]["status"] == "not run"
        assert "--ablations" in ablations[name]["reason"]
    assert "--hobson-url" in ablations["hobson_v21"]["reason"]
    assert ablations["coverage_block_last"]["status"] == "not run"
    assert ablations["k1_vs_k3"]["status"] == "not run"
    text = (paths.results_dir / f"{STEM}.md").read_text(encoding="utf-8")
    assert text.count("NOT RUN") >= 9
    for name in ("haiku_decision", "hobson_v21", "coverage_block_last", "decider_permutation_k3"):
        assert name in text


async def test_a_not_authorised_haiku_reason_is_the_one_given(tmp_path: Path) -> None:
    _, payload = await run_it(tmp_path, haiku_reason="no dollar ceiling authorised (pass it)")
    row = by_name(payload["systems"])["haiku_decision"]
    assert row["status"] == "not run" and "no dollar ceiling" in row["reason"]
    assert "no dollar ceiling" in by_name(payload["systems"])["haiku_plus_rules"]["reason"]


# ------------------------------------------------------------------------- the marker


async def test_the_marker_says_in_progress_while_the_systems_run(tmp_path: Path) -> None:
    snaps = await all_snapshots()
    seen: list[str] = []
    marker = tmp_path / "evaluation" / "results" / "heldout-run.json"

    async def watching(cs: int) -> Any:
        seen.append(json.loads(marker.read_text(encoding="utf-8"))["status"])
        return snaps[cs]

    paths, _ = await run_it(tmp_path, snapshots=watching)
    assert set(seen) == {"in_progress"}
    assert json.loads(marker_path(paths).read_text(encoding="utf-8"))["status"] == "finished"


async def test_a_second_run_is_refused_after_a_finished_one(tmp_path: Path) -> None:
    paths, _ = await run_it(tmp_path)
    with pytest.raises(RunRefused, match="runs once"):
        refuse_if_already_run(paths)
    with pytest.raises(RunRefused, match="appeared while starting|runs once"):
        await run_it(tmp_path)


async def test_a_failed_run_is_marked_failed_writes_no_results_and_still_blocks(
    tmp_path: Path,
) -> None:
    snaps = await all_snapshots()
    calls = 0

    async def breaks(cs: int) -> Any:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise LookupError(cs)
        return snaps[cs]

    with pytest.raises(LookupError):
        await run_it(tmp_path, snapshots=breaks)
    paths = tmp_path / "evaluation"
    marker = json.loads((paths / "results" / "heldout-run.json").read_text(encoding="utf-8"))
    assert marker["status"] == "failed" and marker["error"] == "LookupError"
    assert not list((paths / "results").glob("*-heldout-*"))
    from cso.evaluation.paths import EvalPaths

    with pytest.raises(RunRefused, match="runs once"):
        refuse_if_already_run(EvalPaths(paths))


# ------------------------------------------------------------------------ scored run


GOLD_NATURES = {FIXTURE["04"]: "possible_deliberate_damage"}


async def test_a_scored_run_shows_wilson_intervals_provenance_and_the_harm_rows(
    tmp_path: Path,
) -> None:
    snaps = await all_snapshots()
    gold = gold_for(sorted(snaps), natures=GOLD_NATURES)
    paths, payload = await run_it(tmp_path, gold=gold, labellers=["claude"])
    text = (paths.results_dir / f"{STEM}.md").read_text(encoding="utf-8")
    assert "LABELS: AI-ONLY" in text and NO_GOLD not in text
    assert "Macro-F1" in text and "Accuracy (Wilson 95%)" in text
    assert not INTERVAL.search(text) and not PERCENT.search(text)  # every proportion has a CI
    harm = {(r["system"], r["rules"]): r for r in payload["harm"]["rows"]}
    on = harm[("decider_panel_composed", "on")]
    off = harm[("decider_panel_rules_off", "off")]
    advisory = harm[("decider_advisory_nature", "off")]
    assert (on["rule_eligible"]["k"], on["rule_eligible"]["n"]) == (0, 3)
    # rules off removes the rule hits only: the composition's own caution from parsed evidence stays
    assert (off["rule_eligible"]["k"], off["rule_eligible"]["n"]) == (0, 3)
    assert (on["gold_damage"]["k"], on["gold_damage"]["n"]) == (0, 1)
    # the model's raw advisory nature is the comparison with no safeguard: it reassures all three
    assert (advisory["rule_eligible"]["k"], advisory["rule_eligible"]["n"]) == (3, 3)
    assert (advisory["gold_damage"]["k"], advisory["gold_damage"]["n"]) == (1, 1)
    assert "keeps its own caution from parsed evidence" in text
    rules_only = harm[("rule_baseline_v1", "rules only")]
    assert rules_only["rule_eligible"]["k"] == 0


async def test_a_person_among_the_labellers_makes_the_banner_mixed(tmp_path: Path) -> None:
    snaps = await all_snapshots()
    _, payload = await run_it(
        tmp_path, gold=gold_for(sorted(snaps)), labellers=["claude", "Yogesh"]
    )
    assert payload["labels"]["provenance"].startswith("LABELS: MIXED")
    assert "Yogesh" in payload["labels"]["provenance"]


async def test_with_no_damage_in_the_gold_the_gold_damage_rate_is_undefined_not_zero(
    tmp_path: Path,
) -> None:
    snaps = await all_snapshots()
    paths, payload = await run_it(tmp_path, gold=gold_for(sorted(snaps)), labellers=["claude"])
    text = (paths.results_dir / f"{STEM}.md").read_text(encoding="utf-8")
    assert "undefined (n=0)" in text
    for row in payload["harm"]["rows"]:
        assert row["gold_damage"]["n"] == 0
    assert "0%" not in text.replace("95%", "")


async def test_label_free_harm_rows_say_gold_is_needed_and_keep_the_rule_part(
    tmp_path: Path,
) -> None:
    paths, payload = await run_it(tmp_path)
    text = (paths.results_dir / f"{STEM}.md").read_text(encoding="utf-8")
    assert "needs gold labels" in text
    assert all(row["gold_damage"] is None for row in payload["harm"]["rows"])
    on = {(r["system"], r["rules"]): r for r in payload["harm"]["rows"]}
    assert on[("decider_panel_composed", "on")]["rule_eligible"]["n"] == 3


async def test_the_markdown_can_be_re_rendered_from_the_json(tmp_path: Path) -> None:
    snaps = await all_snapshots()
    paths, _ = await run_it(tmp_path, gold=gold_for(sorted(snaps)), labellers=["claude"])
    payload = json.loads((paths.results_dir / f"{STEM}.json").read_text(encoding="utf-8"))
    assert render_heldout(payload) == (paths.results_dir / f"{STEM}.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- Haiku


async def test_the_haiku_systems_run_with_the_rules_as_a_floor_and_are_costed(
    tmp_path: Path,
) -> None:
    haiku, runtime = fake_haiku()  # always: consistent edit, no action
    paths, payload = await run_it(tmp_path, haiku=haiku, authorize=5.0)
    systems = by_name(payload["systems"])
    assert systems["haiku_decision"]["status"] == "ran"
    assert systems["haiku_decision"]["n_answered"] == 8 and len(runtime.calls) == 8
    assert systems["haiku_plus_rules"]["extra"]["rules_overrode"] == 3  # the three rule items
    cost = payload["cost"]
    assert cost["n_haiku"] == 8
    assert cost["haiku_usd_per_review"] == pytest.approx(estimate_usd(600, 20))
    harm = {(r["system"], r["rules"]): r for r in payload["harm"]["rows"]}
    assert harm[("haiku_decision", "off")]["rule_eligible"]["k"] == 3  # reassures the rule items
    assert harm[("haiku_plus_rules", "on")]["rule_eligible"]["k"] == 0  # the floor stops that
    text = (paths.results_dir / f"{STEM}.md").read_text(encoding="utf-8")
    assert "haiku_plus_rules" in text and "Estimates, not invoices" in text
    row = payload["items"][0]
    assert {"haiku_nature", "haiku_rules_nature", "haiku_rules_overridden"} <= set(row)


async def test_the_haiku_system_stops_at_the_authorised_ceiling_and_says_so(
    tmp_path: Path,
) -> None:
    haiku, runtime = fake_haiku(ceiling_usd=estimate_usd(600, 20) * 0.4)
    _, payload = await run_it(tmp_path, haiku=haiku, authorize=0.001)
    row = by_name(payload["systems"])["haiku_decision"]
    assert row["n_answered"] == 1 and len(runtime.calls) == 1
    assert row["extra"]["error_codes"] == {"budget_exhausted": 7}
    assert row["extra"]["authorised_usd"] == 0.001


async def test_a_haiku_failure_is_recorded_per_item_not_guessed(tmp_path: Path) -> None:
    bad = haiku_reply("consistent_edit", "no_action_suggested")
    bad["stopReason"] = "end_turn"
    haiku, _ = fake_haiku(bad)
    _, payload = await run_it(tmp_path, haiku=haiku, authorize=5.0)
    row = by_name(payload["systems"])["haiku_decision"]
    assert row["n_answered"] == 0 and row["n_errors"] == 8
    assert row["extra"]["error_codes"] == {"bedrock_output": 8}


# ------------------------------------------------------------------------- ablations


async def test_ablations_ask_the_panel_with_each_wording_and_report_agreement(
    tmp_path: Path,
) -> None:
    bodies: list[dict[str, Any]] = []
    _, payload = await run_it(tmp_path, ablations=True, bodies=bodies)
    assert len(bodies) == 8 * 5  # the product plus four wordings, one request per item
    asked = {b["questions"]["new_account_first_edits"]["instructions"] for b in bodies}
    assert asked == {
        PANEL_INSTRUCTIONS["new_account_first_edits"],
        *(v["new_account_first_edits"] for v in INSTRUCTION_VARIANTS.values()),
    }
    ablations = by_name(payload["ablations"])
    for name in (WITHOUT_CUES, *PARAPHRASE_NAMES):
        assert ablations[name]["status"] == "ran" and ablations[name]["n_answered"] == 8
    assert ablations["hobson_v21"]["status"] == "not run"
    assert len(payload["paraphrase_agreement"]) == 10  # five variants, pairwise
    first = payload["paraphrase_agreement"][0]
    assert {"k", "n", "lower", "upper"} == set(first["probe_agreement"])


async def test_hobson_runs_only_with_a_second_server(tmp_path: Path) -> None:
    hobson_bodies: list[dict[str, Any]] = []
    _, payload = await run_it(tmp_path, hobson=decider(bodies=hobson_bodies))
    row = by_name(payload["ablations"])["hobson_v21"]
    assert row["status"] == "ran" and row["extra"]["model"] == "hobson-v21 (cuda)"
    assert len(hobson_bodies) == 8
    assert by_name(payload["ablations"])[WITHOUT_CUES]["status"] == "not run"  # not requested


async def test_ablation_results_with_gold_carry_pooled_probe_accuracy(tmp_path: Path) -> None:
    snaps = await all_snapshots()
    _, payload = await run_it(
        tmp_path, ablations=True, gold=gold_for(sorted(snaps)), labellers=["claude"]
    )
    row = by_name(payload["ablations"])[WITHOUT_CUES]
    assert set(row["extra"]["pooled_probe_accuracy"]) == {"k", "n", "lower", "upper"}
    assert row["scored"] is not None


async def test_the_product_provider_is_used_for_every_system(tmp_path: Path) -> None:
    snaps = await all_snapshots()
    asked: list[int] = []

    async def counting(cs: int) -> Any:
        asked.append(cs)
        return snaps[cs]

    haiku, _ = fake_haiku()
    await run_it(tmp_path, snapshots=counting, haiku=haiku, authorize=5.0)
    assert sorted(set(asked)) == sorted(snaps)
    assert provider(snaps) is not None

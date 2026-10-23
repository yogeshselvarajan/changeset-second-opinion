"""Fact-panel evaluation: label schema v2, panel labelling, scoring, gate, diagnostic and runner."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from cso.adapters.decider import DeciderClient
from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.fixtures import load_case
from cso.domain.models import EvidenceSnapshot
from cso.domain.panel import PANEL_INSTRUCTIONS, PANEL_NOUL_IDS
from cso.evaluation import eval_cli
from cso.evaluation.eval_cli import _cmd_panel_diagnostic, _cmd_spike
from cso.evaluation.label_cli import (
    adjudication_prompt_probes,
    ask_probe,
    label_panel_session,
)
from cso.evaluation.labels import (
    LABELLED_PROBES,
    NOT_COLLECTED,
    GoldLabel,
    LabelError,
    LabelRow,
    LabelStore,
    adjudicate,
    load_gold,
    write_gold,
)
from cso.evaluation.panel_eval import (
    PANEL_POOLED_LOWER_BOUND,
    PanelItemRun,
    diagnose_panel,
    evaluate_panel_gate,
    histogram,
    run_panel_items,
    summarise_panel,
)
from cso.evaluation.panel_report import (
    DIAGNOSTIC_BANNER,
    label_provenance,
    render_diagnostic,
    render_panel_spike,
)
from cso.evaluation.paths import EVAL_DIR_ENV, EvalPaths
from cso.evaluation.split import Split, write_frozen
from cso.settings import Settings

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "backend" / "fixtures" / "cases"
CONFIG = CommunityConfig.load()
GOOD_UA = "ChangesetSecondOpinion/0.1 (+https://example.org/repo; someone@example.org)"
HEALTH = {
    "status": "ok",
    "model": "strands-decider-2B-qwen3.5-v1-2610",
    "checkpoint": "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610",
    "base_model": "Qwen/Qwen3.5-2B-Base",
    "num_slots": 24,
    "max_length": 4096,
    "temperature": 1.0,
    "device": "cuda",
    "prefix_cache": True,
}


def all_probes(answer: str) -> dict[str, str]:
    return dict.fromkeys(LABELLED_PROBES, answer)


async def snapshot_of(prefix: str) -> EvidenceSnapshot:
    case_dir = next(d for d in CASES.iterdir() if d.name.startswith(prefix))
    return await collect(ReplayClient(case_dir), load_case(case_dir).expected.changeset_id)


# ------------------------------------------------------------------------- label schema v2


def test_version_2_label_roundtrips_and_is_marked_version_2(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels.jsonl", "dev")
    row = store.append(
        changeset_id=5,
        labeller="a",
        session="s1",
        nature="consistent_edit",
        probes=all_probes("no"),
    )
    assert row.version == 2 and row.response == NOT_COLLECTED
    (loaded,) = store.rows()
    assert loaded == row
    raw = json.loads((tmp_path / "labels.jsonl").read_text(encoding="utf-8"))
    assert raw["version"] == 2 and set(raw["probes"]) == set(LABELLED_PROBES)


def test_version_1_rows_still_load_and_stay_version_1(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"
    path.write_text(
        json.dumps(
            {
                "set": "dev",
                "changeset_id": 7,
                "labeller": "a",
                "session": "s",
                "nature": "consistent_edit",
                "response": "no_action_suggested",
                "ts": "2026-10-17T00:00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (row,) = LabelStore(path, "dev").rows()
    assert (row.version, dict(row.probes)) == (1, {})
    assert "version" not in row.to_json()


def test_version_2_label_validation_is_explicit(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "l.jsonl", "dev")
    with pytest.raises(LabelError, match="cover exactly"):
        store.append(changeset_id=1, labeller="a", session="s", nature="consistent_edit", probes={})
    with pytest.raises(LabelError, match="unknown answer"):
        store.append(
            changeset_id=1,
            labeller="a",
            session="s",
            nature="consistent_edit",
            probes=all_probes("maybe"),
        )
    with pytest.raises(LabelError, match="nature"):
        store.append(
            changeset_id=1, labeller="a", session="s", nature="vague", probes=all_probes("yes")
        )
    # without probes the old rubric still applies and a version 1 row needs a real response
    with pytest.raises(LabelError, match="response"):
        store.append(changeset_id=1, labeller="a", session="s", nature="consistent_edit")
    assert not (tmp_path / "l.jsonl").exists()  # nothing was written for any rejected label


def test_labels_are_append_only_and_the_latest_row_is_effective(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "l.jsonl", "dev")
    store.append(
        changeset_id=1, labeller="a", session="s", nature="consistent_edit", probes=all_probes("no")
    )
    store.append(
        changeset_id=1,
        labeller="a",
        session="s",
        nature="ambiguous",
        probes=all_probes("unknown"),
    )
    assert len(store.rows()) == 2
    assert store.effective("a", "s")[1].nature == "ambiguous"


def _two_sessions(tmp_path: Path) -> LabelStore:
    store = LabelStore(tmp_path / "l.jsonl", "dev")
    same = all_probes("no")
    other = {**same, "mature_feature_deleted": "yes"}
    for session, probes_two in (("s1", other), ("s2", same)):
        store.append(
            changeset_id=1,
            labeller="a",
            session=session,
            nature="consistent_edit",
            probes=same,
        )
        store.append(
            changeset_id=2,
            labeller="a",
            session=session,
            nature="needs_local_knowledge",
            probes=probes_two,
        )
    return store


def test_adjudication_merges_agreeing_items_and_asks_about_probe_disagreements(
    tmp_path: Path,
) -> None:
    store = _two_sessions(tmp_path)
    asked: list[int] = []

    def decide(cs: int, a: LabelRow, b: LabelRow) -> tuple[str, dict[str, str]]:
        asked.append(cs)
        return a.nature, dict(b.probes)

    gold, agreement = adjudicate(
        store,
        session_a=("a", "s1"),
        session_b=("a", "s2"),
        decide=lambda *_: ("x", "y"),
        decide_probes=decide,
        adjudicator="adj",
    )
    assert asked == [2]
    assert [(g.changeset_id, g.method, g.version) for g in gold] == [
        (1, "agree", 2),
        (2, "adjudicated", 2),
    ]
    assert agreement.probe_items == 2
    assert agreement.probe_agree["mature_feature_deleted"] == 1
    assert agreement.probe_agree["conventions_followed"] == 2
    write_gold(tmp_path / "gold.jsonl", gold)
    assert load_gold(tmp_path / "gold.jsonl")[2].probes["mature_feature_deleted"] == "no"


def test_version_2_disagreement_without_a_probe_adjudicator_is_refused(tmp_path: Path) -> None:
    store = _two_sessions(tmp_path)
    with pytest.raises(LabelError, match="no probe adjudication"):
        adjudicate(
            store,
            session_a=("a", "s1"),
            session_b=("a", "s2"),
            decide=lambda *_: ("x", "y"),
            adjudicator="adj",
        )


# ------------------------------------------------------------------------- panel labelling


def scripted(answers: list[str]) -> Callable[[str], str]:
    queue = iter(answers)
    return lambda _prompt: next(queue)


def test_ask_probe_accepts_letters_words_and_numbers() -> None:
    lines: list[str] = []
    for typed, expected in (("y", "yes"), ("No", "no"), ("u", "unknown"), ("2", "no")):
        assert ask_probe("q", input_fn=scripted([typed]), print_fn=lines.append) == expected
    assert ask_probe("q", input_fn=scripted(["x", "y"]), print_fn=lines.append) == "yes"
    assert any("enter y, n or u" in line for line in lines)


async def test_panel_labelling_collects_nature_and_every_probe_and_shows_no_model_output(
    tmp_path: Path,
) -> None:
    snapshot = await snapshot_of("01")
    cs = snapshot.changeset.id
    store = LabelStore(tmp_path / "l.jsonl", "dev")
    out: list[str] = []
    answers = ["1"] + ["n"] * len(LABELLED_PROBES)  # nature 1 = consistent_edit
    labelled = label_panel_session(
        store=store,
        ids=[cs],
        snapshots=lambda _cs: snapshot,
        config=CONFIG,
        labeller="a",
        session="s1",
        input_fn=scripted(answers),
        print_fn=out.append,
    )
    assert labelled == 1
    (row,) = store.rows()
    assert row.version == 2 and row.nature == "consistent_edit"
    assert set(row.probes) == set(LABELLED_PROBES) and set(row.probes.values()) == {"no"}
    shown = "\n".join(out)
    assert "COVERAGE" in shown and "SUMMARY" in shown  # the compact text the model also reads
    for probe_id in LABELLED_PROBES:
        assert PANEL_INSTRUCTIONS[probe_id] in shown
    for leaked in ("advisory", "composed", "probability", "Decider", "weak", "R1"):
        assert leaked not in shown, leaked


async def test_panel_labelling_resumes_and_quits(tmp_path: Path) -> None:
    snapshot = await snapshot_of("01")
    cs = snapshot.changeset.id
    store = LabelStore(tmp_path / "l.jsonl", "dev")
    kwargs: dict[str, Any] = {
        "store": store,
        "ids": [cs],
        "snapshots": lambda _cs: snapshot,
        "config": CONFIG,
        "labeller": "a",
        "session": "s1",
        "print_fn": lambda _msg: None,
    }
    assert label_panel_session(input_fn=scripted(["q"]), **kwargs) == 0
    assert not store.rows()
    assert label_panel_session(input_fn=scripted(["1", *["y"] * 9]), **kwargs) == 1
    assert label_panel_session(input_fn=scripted([]), **kwargs) == 0  # already done


async def test_probe_adjudication_reasks_only_the_differing_fields() -> None:
    snapshot = await snapshot_of("01")
    a = LabelRow("dev", 1, "a", "s1", "consistent_edit", NOT_COLLECTED, "t", 2, all_probes("no"))
    b_probes = {**all_probes("no"), "conventions_followed": "yes"}
    b = LabelRow("dev", 1, "a", "s2", "consistent_edit", NOT_COLLECTED, "t", 2, b_probes)
    lines: list[str] = []
    decide = adjudication_prompt_probes(
        snapshots=lambda _cs: snapshot,
        config=CONFIG,
        input_fn=scripted(["u"]),  # exactly one question is asked
        print_fn=lines.append,
    )
    nature, probes = decide(1, a, b)
    assert nature == "consistent_edit"
    assert probes["conventions_followed"] == "unknown"
    assert {k: v for k, v in probes.items() if k != "conventions_followed"} == {
        k: "no" for k in LABELLED_PROBES if k != "conventions_followed"
    }


# ------------------------------------------------------------------------ scoring and gate


def run_of(
    cs: int,
    states: dict[str, str],
    *,
    nature: str = "consistent_edit",
    rules_nature: str = "consistent_edit",
    advisory: str = "consistent_edit",
) -> PanelItemRun:
    full = dict.fromkeys(PANEL_NOUL_IDS, "no") | states
    return PanelItemRun(
        changeset_id=cs,
        rules_nature=rules_nature,
        rules_response="no_action_suggested",
        rules_fired=(),
        probabilities={i: {"yes": 0.9, "no": 0.1, "unknown": 0.5}[s] for i, s in full.items()},
        states=full,
        composed_nature=nature,
        composed_response="no_action_suggested",
        composed_lane="looks_consistent",
        composed_band="confident",
        nature_row="N4",
        response_row="P5",
        advisory_choice=advisory,
        advisory_confidence=0.3,
        input_tokens=1500,
        latency_ms=1000,
        server_latency_ms=450.0,
    )


def gold_of(cs: int, nature: str, probes: dict[str, str]) -> GoldLabel:
    return GoldLabel(
        "dev",
        cs,
        nature,
        NOT_COLLECTED,
        "agree",
        None,
        "t",
        version=2,
        probes={**all_probes("no"), **probes},
    )


def test_panel_scoring_counts_decided_accuracy_unknowns_and_excludes_gold_unknown() -> None:
    probe = "mature_feature_deleted"
    runs = [
        run_of(1, {probe: "yes"}),
        run_of(2, {probe: "no"}),
        run_of(3, {probe: "unknown"}),
        run_of(4, {probe: "yes"}),
        run_of(5, {probe: "yes"}),
    ]
    gold = {
        1: gold_of(1, "consistent_edit", {probe: "yes"}),  # correct
        2: gold_of(2, "consistent_edit", {probe: "yes"}),  # wrong
        3: gold_of(3, "consistent_edit", {probe: "yes"}),  # panel unknown
        4: gold_of(4, "consistent_edit", {probe: "unknown"}),  # gold unknown: excluded
        5: gold_of(5, "ambiguous", {probe: "no"}),  # wrong, and ambiguous nature
    }
    summary = summarise_panel(runs, gold)
    score = next(s for s in summary.probes if s.probe == probe)
    assert score.n_gold == 4
    assert (score.accuracy_decided.k, score.accuracy_decided.n) == (1, 3)
    assert (score.panel_unknown.k, score.panel_unknown.n) == (1, 4)
    assert (score.accuracy_strict.k, score.accuracy_strict.n) == (1, 4)
    assert summary.n_labelled == 5 and summary.n_scored == 4  # the ambiguous item is not scored
    assert summary.ambiguous.k == 1
    for proportion in (score.accuracy_decided, summary.pooled_decided):
        assert 0.0 <= proportion.lower <= proportion.upper <= 1.0  # Wilson interval present


def test_failed_panel_runs_are_counted_and_never_scored() -> None:
    failed = PanelItemRun(1, "consistent_edit", "no_action_suggested", (), error="DeciderTimeout")
    summary = summarise_panel([failed], {1: gold_of(1, "consistent_edit", {})})
    assert summary.n_failures == 1 and summary.n_scored == 0


def test_version_1_gold_is_ignored_by_the_panel_summary() -> None:
    old = GoldLabel("dev", 1, "consistent_edit", "no_action_suggested", "agree", None, "t")
    assert summarise_panel([run_of(1, {})], {1: old}).n_labelled == 0


def _scored_dataset(*, correct: int, n: int, composed_right: bool) -> tuple[list, dict]:
    """`correct` of `n` items have every probe right; the rule baseline is always wrong."""
    runs, gold = [], {}
    for i in range(1, n + 1):
        truth = "yes" if i % 2 == 0 else "no"
        said = truth if i <= correct else ("no" if truth == "yes" else "yes")
        nature = "consistent_edit" if composed_right else "possible_deliberate_damage"
        runs.append(
            run_of(
                i,
                dict.fromkeys(LABELLED_PROBES, said),
                nature=nature,
                rules_nature="possible_deliberate_damage",
            )
        )
        gold[i] = gold_of(i, "consistent_edit", dict.fromkeys(LABELLED_PROBES, truth))
    return runs, gold


@pytest.mark.parametrize(
    ("correct", "composed_right", "verdict"),
    [(60, True, "GO"), (60, False, "BORDERLINE"), (20, True, "BORDERLINE"), (20, False, "NO-GO")],
)
def test_panel_gate_needs_both_conditions(correct: int, composed_right: bool, verdict: str) -> None:
    runs, gold = _scored_dataset(correct=correct, n=60, composed_right=composed_right)
    gate = evaluate_panel_gate(summarise_panel(runs, gold))
    assert gate.f1_condition is composed_right
    assert gate.pooled_condition is (correct == 60)
    assert gate.pooled_condition == (gate.pooled_lower >= PANEL_POOLED_LOWER_BOUND)
    assert gate.verdict == verdict


def test_panel_spike_report_has_one_verdict_line_and_states_the_gate() -> None:
    runs, gold = _scored_dataset(correct=60, n=60, composed_right=True)
    summary = summarise_panel(runs, gold)
    gate = evaluate_panel_gate(summary)
    text = render_panel_spike(summary, gate, date="d", config_version="v", model="m")
    assert sum(1 for line in text.splitlines() if line.startswith("VERDICT:")) == 1
    assert "ADR-009" in text and "Wilson" in text


def test_ai_only_provenance_is_on_the_verdict_line_and_replaces_the_hand_label_note() -> None:
    runs, gold = _scored_dataset(correct=60, n=60, composed_right=True)
    summary = summarise_panel(runs, gold)
    gate = evaluate_panel_gate(summary)
    banner = label_provenance(["claude"], ["claude"])
    text = render_panel_spike(
        summary, gate, date="d", config_version="v", model="m", provenance=banner
    )
    verdict = next(line for line in text.splitlines() if line.startswith("VERDICT:"))
    assert "AI-ONLY LABELS" in verdict
    assert "LABELS: AI-ONLY" in text
    assert "hand labels by the authors" not in text
    mixed = render_panel_spike(
        summary,
        gate,
        date="d",
        config_version="v",
        model="m",
        provenance=label_provenance(["claude", "Yogesh"], []),
    )
    assert "AI-ONLY LABELS" not in next(
        line for line in mixed.splitlines() if line.startswith("VERDICT:")
    )


# --------------------------------------------------------------------------- diagnostic


def test_histogram_bins_cover_zero_to_one_with_one_in_the_last_bin() -> None:
    assert histogram([0.0, 0.05, 0.1, 0.55, 0.99, 1.0]) == (2, 1, 0, 0, 0, 1, 0, 0, 0, 2)
    assert sum(histogram([i / 100 for i in range(101)])) == 101


def test_diagnostic_reports_near_half_share_failures_and_parsed_agreement() -> None:
    near = run_of(1, {"nonsense_or_offensive_values": "unknown"})
    far = run_of(2, {})
    agree = PanelItemRun(
        3,
        "consistent_edit",
        "no_action_suggested",
        (),
        probabilities={i: 0.1 for i in PANEL_NOUL_IDS},
        states=dict.fromkeys(PANEL_NOUL_IDS, "no"),
        composed_nature="consistent_edit",
        cross_checks={"mature_feature_deleted": "agree", "mass_retag_single_key": "disagree"},
        input_tokens=1000,
        latency_ms=900,
    )
    failed = PanelItemRun(4, "consistent_edit", "no_action_suggested", (), error="DeciderTimeout")
    diag = diagnose_panel([near, far, agree, failed], CONFIG)
    assert (diag.n_items, diag.n_answered, diag.n_failures) == (4, 3, 1)
    nonsense = next(p for p in diag.probes if p.probe == "nonsense_or_offensive_values")
    assert (nonsense.near_half.k, nonsense.near_half.n) == (1, 3)
    mature = next(a for a in diag.agreement if a.probe == "mature_feature_deleted")
    assert (mature.agree, mature.disagree) == (1, 0)
    mass = next(a for a in diag.agreement if a.probe == "mass_retag_single_key")
    assert mass.disagree == 1 and mass.agreement_decided.k == 0
    assert diag.input_tokens_p50 is not None and diag.latency.n == 3


def test_diagnostic_report_is_marked_as_no_verdict_and_carries_no_names() -> None:
    diag = diagnose_panel([run_of(1, {}), run_of(2, {})], CONFIG)
    text = render_diagnostic(
        diag, date="d", config_version="v", model="m", profile="compact", split_status="s"
    )
    assert DIAGNOSTIC_BANNER in text
    assert not any(line.startswith("VERDICT") for line in text.splitlines())
    assert "NOT A VERDICT" in text and "held-out" in text.lower()
    for probe_id in PANEL_NOUL_IDS:
        assert probe_id in text


# ----------------------------------------------------------------------------------- runner


def panel_server(calls: list[str], *, fail: bool = False) -> DeciderClient:
    probs = {c.code: 0.25 for c in CONFIG.option_sets.nature}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json=HEALTH)
        if fail:
            return httpx.Response(503, json={"detail": "down"})
        answers: dict[str, Any] = {
            "nature": {
                "type": "choice",
                "choice": "consistent_edit",
                "probabilities": probs,
                "confidence": 0.1,
            }
        }
        for noul_id in PANEL_NOUL_IDS:
            answers[noul_id] = {"type": "noul", "noul": 0.1}
        answers["comment_matches_changes"] = {"type": "noul", "noul": 0.9}
        answers["conventions_followed"] = {"type": "noul", "noul": 0.9}
        body = {
            "model": HEALTH["model"],
            "answers": answers,
            "usage": {"input_tokens": 700, "output_tokens": 0},
            "latency_ms": 250.0,
        }
        return httpx.Response(200, json=body)

    http = httpx.AsyncClient(base_url="http://decider.test", transport=httpx.MockTransport(handler))
    return DeciderClient("http://decider.test", http=http)


async def test_run_panel_items_makes_one_request_per_item_and_writes_number_only_receipts(
    tmp_path: Path,
) -> None:
    snaps = {s.changeset.id: s for s in [await snapshot_of("01"), await snapshot_of("04")]}
    calls: list[str] = []
    client = panel_server(calls)

    async def provider(cs: int) -> EvidenceSnapshot:
        return snaps[cs]

    runs = await run_panel_items(
        sorted(snaps), provider, CONFIG, client, receipts_dir=tmp_path / "r"
    )
    await client.aclose()
    assert calls.count("/v1/systemone") == 2
    by_id = {r.changeset_id: r for r in runs}
    clean, deletion = by_id[900000000001], by_id[900000000004]
    assert clean.composed_nature == "consistent_edit" and clean.composed_lane == "looks_consistent"
    assert deletion.composed_response == "escalate_to_experienced_reviewer"  # R1 decides
    assert deletion.composed_lane == "insufficient_evidence"  # R3 decides
    assert deletion.cross_checks["mature_feature_deleted"] == "disagree"  # model said no, R1 fired
    assert clean.input_tokens == 700 and clean.latency_ms is not None
    receipts = sorted((tmp_path / "r").glob("*.json"))
    assert len(receipts) == 2
    for path in receipts:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["profile"] == "compact" and "panel" in data and "composition" in data
        assert "evidence" not in data and "rendered_text" not in data


async def test_run_panel_items_records_a_decider_failure_and_never_guesses(tmp_path: Path) -> None:
    snap = await snapshot_of("01")
    client = panel_server([], fail=True)

    async def provider(_cs: int) -> EvidenceSnapshot:
        return snap

    (run,) = await run_panel_items(
        [snap.changeset.id], provider, CONFIG, client, receipts_dir=tmp_path
    )
    await client.aclose()
    assert run.error is not None
    assert run.composed_nature is None and run.states is None
    assert not list(tmp_path.glob("*.json"))


# ------------------------------------------------------------------------------- commands


def settings_with(**values: Any) -> Callable[[], Settings]:
    return lambda: Settings(**values)


def test_panel_diagnostic_refuses_a_placeholder_user_agent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(
        eval_cli,
        "get_settings",
        settings_with(user_agent="ChangesetSecondOpinion/0.1 (+<REPO_URL>; <CONTACT_EMAIL>)"),
    )
    args = argparse.Namespace(set="all", profile="compact")
    assert _cmd_panel_diagnostic(args) == 1
    assert "CSO_USER_AGENT" in capsys.readouterr().err


def test_panel_diagnostic_needs_a_decider_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(eval_cli, "get_settings", settings_with(user_agent=GOOD_UA))
    args = argparse.Namespace(set="all", profile="compact")
    assert _cmd_panel_diagnostic(args) == 1
    assert "CSO_DECIDER_URL" in capsys.readouterr().err


def test_panel_diagnostic_writes_a_report_without_labels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    paths = EvalPaths(tmp_path)
    paths.candidates.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "account_age": "lt1y",
            "changeset_id": cs,
            "coverage_score": 1.0,
            "created_at": "2026-06-04",
            "deletes": 0,
            "elements": 1,
            "flags": [],
            "mapper_hash": f"{cs:016x}",
            "source": "maproulette",
            "weak_mr_status": "false_positive",
        }
        for cs in (11, 12)
    ]
    paths.candidates.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(
        eval_cli, "get_settings", settings_with(user_agent=GOOD_UA, decider_url="http://x")
    )

    async def fake_runs(**kwargs: Any) -> tuple[list[PanelItemRun], str]:
        assert kwargs["ids"] == [11, 12] and kwargs["profile"] == "compact"
        return [run_of(11, {}), run_of(12, {"nonsense_or_offensive_values": "unknown"})], "m (cpu)"

    monkeypatch.setattr(eval_cli, "_panel_runs", fake_runs)
    assert _cmd_panel_diagnostic(argparse.Namespace(set="all", profile="compact")) == 0
    (report,) = paths.results_dir.glob("panel-diagnostic-*.md")
    body = report.read_text(encoding="utf-8")
    assert DIAGNOSTIC_BANNER in body and "2/2" not in body.splitlines()[0]
    assert not paths.labels_dir.exists()  # no labels read or written
    (data_file,) = paths.results_dir.glob("panel-diagnostic-*.json")
    assert json.loads(data_file.read_text(encoding="utf-8"))["set"] == "all"


def test_panel_spike_without_version_2_labels_is_not_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    paths = EvalPaths(tmp_path)
    write_frozen(paths, Split(tuple(range(1, 61)), (1001, 1002), ()))
    gold = [
        GoldLabel("dev", i, "consistent_edit", "no_action_suggested", "agree", None, "t")
        for i in range(1, 61)
    ]
    write_gold(paths.adjudicated("dev"), gold)  # sixty version 1 labels: the wrong schema
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    assert _cmd_spike(argparse.Namespace(contract="panel")) == 0
    assert "NOT RUN: insufficient labels (0/60)" in capsys.readouterr().out
    (report,) = paths.results_dir.glob("spike-*.md")
    assert "VERDICT" not in report.read_text(encoding="utf-8")

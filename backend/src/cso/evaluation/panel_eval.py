"""Run the fact panel over changesets and summarise it (ADR-009 decision contract).

Three things live here: `run_panel_items` (rule baseline plus one Decider panel request per item),
`summarise_panel` with its go/no-go gate (needs adjudicated version 2 labels), and
`diagnose_panel` (label-free statistics: probability histograms, share near 0.5, tokens, latency
and agreement with the facts computed from parsed evidence). The diagnostic is never a verdict.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from cso.adapters.decider import DeciderClient, DeciderError, PanelResult
from cso.domain.config import CommunityConfig
from cso.domain.evidence import Profile, render
from cso.domain.lanes import assign_lane, compose_panel, evaluate_panel_run
from cso.domain.models import EvidenceSnapshot
from cso.domain.panel import ADVISORY_PROBES, PANEL_NOUL_IDS
from cso.domain.policy import parsed_facts
from cso.evaluation.baselines import rule_baseline
from cso.evaluation.labels import AMBIGUOUS, LABELLED_PROBES, GoldLabel
from cso.evaluation.paths import write_text_lf
from cso.evaluation.runner import SystemScore, score_system
from cso.evaluation.spike import (
    F1_MARGIN,
    NATURES,
    LatencySummary,
)
from cso.evaluation.stats import Proportion, proportion, quantile

SnapshotProvider = Callable[[int], Awaitable[EvidenceSnapshot]]
PanelDecide = Callable[[str, CommunityConfig], Awaitable[PanelResult]]

PANEL_POOLED_LOWER_BOUND = 0.70
HISTOGRAM_BINS = 10
NEAR_HALF = (0.4, 0.6)
DERIVABLE_PROBES = (
    "mature_feature_deleted",
    "new_account_first_edits",
    "mass_retag_single_key",
    "evidence_sufficient",
)


@dataclass(frozen=True)
class PanelItemRun:
    """Rule baseline and the fact panel for one changeset (panel fields None when it failed)."""

    changeset_id: int
    rules_nature: str
    rules_response: str
    rules_fired: tuple[str, ...]
    probabilities: dict[str, float] | None = None
    states: dict[str, str] | None = None
    composed_nature: str | None = None
    composed_response: str | None = None
    composed_lane: str | None = None
    composed_band: str | None = None
    nature_row: str | None = None
    response_row: str | None = None
    advisory_choice: str | None = None
    advisory_confidence: float | None = None
    cross_checks: dict[str, str] = field(default_factory=dict)
    # The same panel composed with every rule hit removed ("rules off"), for the safety metrics.
    norules_nature: str | None = None
    norules_response: str | None = None
    norules_lane: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    server_latency_ms: float | None = None
    error: str | None = None


async def run_panel_items(
    ids: Sequence[int],
    snapshots: SnapshotProvider,
    config: CommunityConfig,
    decider: DeciderClient,
    *,
    profile: Profile = "compact",
    receipts_dir: Path | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    decide: PanelDecide | None = None,
) -> list[PanelItemRun]:
    """One panel request per changeset; a Decider failure is recorded, never replaced by a guess.

    Every success writes `receipts_dir/<changeset>.json` with numbers only (no evidence text).
    `decide` replaces `decider.decide_panel` (ablations ask the same panel with other wording).
    """
    ask: PanelDecide = decide if decide is not None else decider.decide_panel
    runs: list[PanelItemRun] = []
    for n, cs in enumerate(ids, start=1):
        snapshot = await snapshots(cs)
        rules = rule_baseline(snapshot, config)
        base = PanelItemRun(
            changeset_id=cs,
            rules_nature=rules.nature.value,
            rules_response=rules.response.value,
            rules_fired=rules.fired,
        )
        rendered = render(snapshot, config, profile=profile)
        try:
            result = await ask(rendered.text, config)
        except DeciderError as exc:
            runs.append(replace(base, error=f"{type(exc).__name__}: {str(exc)[:200]}"))
            progress(f"[{n}/{len(ids)}] {cs}: decider error {type(exc).__name__}")
            continue
        outcome = evaluate_panel_run(snapshot, result.panel, config)
        composition = outcome.composition
        if composition is None:  # a panel run always has a composition
            raise RuntimeError("panel outcome has no composition")
        advisory = result.panel.advisory_nature
        bare = compose_panel(result.panel, [], config, parsed_facts(snapshot, config))
        bare_lane = assign_lane(bare.band, bare.nature, bare.response, [])
        runs.append(
            replace(
                base,
                probabilities={i: r.probability for i, r in result.panel.readings.items()},
                states={i: r.state.value for i, r in result.panel.readings.items()},
                composed_nature=composition.nature.value,
                composed_response=composition.response.value,
                composed_lane=outcome.lane.value,
                composed_band=composition.band.value,
                nature_row=composition.nature_row,
                response_row=composition.response_row,
                advisory_choice=advisory.choice,
                advisory_confidence=advisory.confidence,
                cross_checks=dict(outcome.cross_checks),
                norules_nature=bare.nature.value,
                norules_response=bare.response.value,
                norules_lane=bare_lane.value,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                server_latency_ms=result.server_latency_ms,
            )
        )
        if receipts_dir is not None:
            write_text_lf(
                receipts_dir / f"{cs}.json",
                json.dumps(
                    {
                        "changeset_id": cs,
                        "config_version": config.version,
                        "evidence_version": snapshot.evidence_version,
                        "profile": profile,
                        "rendered_tokens_estimate": rendered.estimated_tokens,
                        "questions_hash": result.questions_hash,
                        "identity": result.identity.model_dump(mode="json"),
                        "panel": result.panel.model_dump(mode="json"),
                        "composition": {
                            "nature": composition.nature.value,
                            "response": composition.response.value,
                            "band": composition.band.value,
                            "nature_row": composition.nature_row,
                            "response_row": composition.response_row,
                            "lane": outcome.lane.value,
                            "rules": [h.code for h in outcome.rule_hits],
                            "cross_checks": dict(outcome.cross_checks),
                        },
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "server_latency_ms": result.server_latency_ms,
                        "latency_ms": result.latency_ms,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
        progress(f"[{n}/{len(ids)}] {cs}: ok {result.latency_ms} ms")
    return runs


# ------------------------------------------------------------------------------ scored summary


@dataclass(frozen=True)
class ProbeScore:
    """One probe against the hand labels (gold yes/no only; gold unknown is excluded)."""

    probe: str
    n_gold: int
    panel_unknown: Proportion  # panel read unknown, among items with a yes/no gold answer
    accuracy_decided: Proportion  # correct among items where the panel said yes or no
    accuracy_strict: Proportion  # correct among all gold yes/no items (unknown counts wrong)


@dataclass(frozen=True)
class PanelSummary:
    """Per-probe accuracy, composed-nature macro-F1 and the baseline, on adjudicated labels."""

    n_labelled: int
    n_scored: int
    n_failures: int
    ambiguous: Proportion
    probes: tuple[ProbeScore, ...]
    pooled_decided: Proportion
    composed_nature: SystemScore
    advisory_nature: SystemScore
    rules_nature: SystemScore
    latency: LatencySummary
    input_tokens_p50: float | None
    input_tokens_p95: float | None


def _probe_scores(
    pairs: Sequence[tuple[PanelItemRun, GoldLabel]],
) -> tuple[list[ProbeScore], Proportion]:
    scores: list[ProbeScore] = []
    pooled_k = pooled_n = 0
    for probe in LABELLED_PROBES:
        gold_n = decided_n = decided_k = unknown_n = strict_k = 0
        for run, gold in pairs:
            answer = gold.probes.get(probe)
            if answer not in ("yes", "no") or run.states is None:
                continue
            gold_n += 1
            state = run.states[probe]
            if state == "unknown":
                unknown_n += 1
                continue
            decided_n += 1
            if state == answer:
                decided_k += 1
                strict_k += 1
        scores.append(
            ProbeScore(
                probe=probe,
                n_gold=gold_n,
                panel_unknown=proportion(unknown_n, gold_n),
                accuracy_decided=proportion(decided_k, decided_n),
                accuracy_strict=proportion(strict_k, gold_n),
            )
        )
        pooled_k += decided_k
        pooled_n += decided_n
    return scores, proportion(pooled_k, pooled_n)


def summarise_panel(runs: Sequence[PanelItemRun], gold: dict[int, GoldLabel]) -> PanelSummary:
    """Score the panel on labelled items whose gold row has probe labels (schema version 2)."""
    pairs = [(r, gold[r.changeset_id]) for r in runs if r.changeset_id in gold]
    pairs = [(r, g) for r, g in pairs if g.version >= 2]
    decided = [(r, g) for r, g in pairs if r.error is None and r.composed_nature is not None]
    failures = sum(1 for r, _ in pairs if r.error is not None)
    scored = [(r, g) for r, g in decided if not g.ambiguous]
    truth = [g.nature for _, g in scored]
    probes, pooled = _probe_scores(decided)
    latencies = [float(r.latency_ms) for r, _ in decided if r.latency_ms is not None]
    server = [r.server_latency_ms for r, _ in decided if r.server_latency_ms is not None]
    tokens = [float(r.input_tokens) for r, _ in decided if r.input_tokens is not None]
    return PanelSummary(
        n_labelled=len(pairs),
        n_scored=len(scored),
        n_failures=failures,
        ambiguous=proportion(sum(1 for _, g in pairs if g.nature == AMBIGUOUS), len(pairs)),
        probes=tuple(probes),
        pooled_decided=pooled,
        composed_nature=score_system(truth, [r.composed_nature or "" for r, _ in scored], NATURES),
        advisory_nature=score_system(truth, [r.advisory_choice or "" for r, _ in scored], NATURES),
        rules_nature=score_system(truth, [r.rules_nature for r, _ in scored], NATURES),
        latency=LatencySummary(
            n=len(latencies),
            p50=quantile(latencies, 0.5),
            p95=quantile(latencies, 0.95),
            server_p50=quantile(server, 0.5),
            server_p95=quantile(server, 0.95),
        ),
        input_tokens_p50=quantile(tokens, 0.5),
        input_tokens_p95=quantile(tokens, 0.95),
    )


@dataclass(frozen=True)
class PanelGate:
    """The two panel gate conditions and the verdict (ADR-009)."""

    f1_delta: float
    f1_condition: bool
    pooled_lower: float
    pooled_condition: bool
    verdict: str  # GO | BORDERLINE | NO-GO


def evaluate_panel_gate(summary: PanelSummary) -> PanelGate:
    """Composed-nature macro-F1 beats the rules by 10 points AND pooled probe accuracy >= 0.70."""
    delta = summary.composed_nature.macro_f1 - summary.rules_nature.macro_f1
    f1_ok = delta >= F1_MARGIN - 1e-12
    pooled_ok = (
        summary.pooled_decided.n > 0 and summary.pooled_decided.lower >= PANEL_POOLED_LOWER_BOUND
    )
    met = int(f1_ok) + int(pooled_ok)
    verdict = "GO" if met == 2 else "BORDERLINE" if met == 1 else "NO-GO"
    return PanelGate(delta, f1_ok, summary.pooled_decided.lower, pooled_ok, verdict)


# ----------------------------------------------------------------------- label-free diagnostic


@dataclass(frozen=True)
class ProbeDiagnostic:
    """Distribution of one probe's probability over the items that were answered."""

    probe: str
    n: int
    histogram: tuple[int, ...]
    near_half: Proportion  # probability in [0.4, 0.6]
    unknown: Proportion  # probability in the tri-state middle band
    yes: Proportion
    no: Proportion


@dataclass(frozen=True)
class AgreementDiagnostic:
    """A derivable probe against the fact computed from parsed evidence."""

    probe: str
    agree: int
    disagree: int
    undecided: int
    not_applicable: int
    agreement_decided: Proportion


@dataclass(frozen=True)
class PanelDiagnostic:
    """Label-free statistics over all answered items. Not a verdict."""

    n_items: int
    n_answered: int
    n_failures: int
    probes: tuple[ProbeDiagnostic, ...]
    agreement: tuple[AgreementDiagnostic, ...]
    nature_counts: dict[str, int]
    response_counts: dict[str, int]
    lane_counts: dict[str, int]
    band_counts: dict[str, int]
    rows_counts: dict[str, int]
    advisory_top_p50: float | None
    input_tokens_p50: float | None
    input_tokens_p95: float | None
    latency: LatencySummary


def histogram(values: Sequence[float], bins: int = HISTOGRAM_BINS) -> tuple[int, ...]:
    """Counts in equal-width bins over [0, 1]; the last bin includes 1.0."""
    counts = [0] * bins
    for value in values:
        counts[min(int(value * bins), bins - 1)] += 1
    return tuple(counts)


def diagnose_panel(runs: Sequence[PanelItemRun], config: CommunityConfig) -> PanelDiagnostic:
    """Histograms, near-0.5 shares, composition counts, parsed agreement, tokens and latency."""
    answered = [r for r in runs if r.error is None and r.probabilities is not None]
    low, high = config.panel.thresholds.low, config.panel.thresholds.high
    probes: list[ProbeDiagnostic] = []
    for probe in PANEL_NOUL_IDS:
        values = [r.probabilities[probe] for r in answered if r.probabilities is not None]
        n = len(values)
        probes.append(
            ProbeDiagnostic(
                probe=probe,
                n=n,
                histogram=histogram(values),
                near_half=proportion(
                    sum(1 for v in values if NEAR_HALF[0] <= v <= NEAR_HALF[1]), n
                ),
                unknown=proportion(sum(1 for v in values if low <= v <= high), n),
                yes=proportion(sum(1 for v in values if v > high), n),
                no=proportion(sum(1 for v in values if v < low), n),
            )
        )
    agreement: list[AgreementDiagnostic] = []
    for probe in DERIVABLE_PROBES:
        votes = Counter(r.cross_checks.get(probe, "n/a") for r in answered)
        decided = votes["agree"] + votes["disagree"]
        agreement.append(
            AgreementDiagnostic(
                probe=probe,
                agree=votes["agree"],
                disagree=votes["disagree"],
                undecided=votes["undecided"],
                not_applicable=votes["n/a"],
                agreement_decided=proportion(votes["agree"], decided),
            )
        )
    latencies = [float(r.latency_ms) for r in answered if r.latency_ms is not None]
    server = [r.server_latency_ms for r in answered if r.server_latency_ms is not None]
    tokens = [float(r.input_tokens) for r in answered if r.input_tokens is not None]
    advisory = [r.advisory_confidence for r in answered if r.advisory_confidence is not None]
    return PanelDiagnostic(
        n_items=len(runs),
        n_answered=len(answered),
        n_failures=sum(1 for r in runs if r.error is not None),
        probes=tuple(probes),
        agreement=tuple(agreement),
        nature_counts=dict(Counter(r.composed_nature for r in answered if r.composed_nature)),
        response_counts=dict(Counter(r.composed_response for r in answered if r.composed_response)),
        lane_counts=dict(Counter(r.composed_lane for r in answered if r.composed_lane)),
        band_counts=dict(Counter(r.composed_band for r in answered if r.composed_band)),
        rows_counts=dict(
            Counter(f"{r.nature_row}/{r.response_row}" for r in answered if r.nature_row)
        ),
        advisory_top_p50=quantile(advisory, 0.5),
        input_tokens_p50=quantile(tokens, 0.5),
        input_tokens_p95=quantile(tokens, 0.95),
        latency=LatencySummary(
            n=len(latencies),
            p50=quantile(latencies, 0.5),
            p95=quantile(latencies, 0.95),
            server_p50=quantile(server, 0.5),
            server_p95=quantile(server, 0.95),
        ),
    )


__all__ = [
    "ADVISORY_PROBES",
    "DERIVABLE_PROBES",
    "AgreementDiagnostic",
    "PanelDiagnostic",
    "PanelGate",
    "PanelItemRun",
    "PanelSummary",
    "ProbeDiagnostic",
    "ProbeScore",
    "diagnose_panel",
    "evaluate_panel_gate",
    "histogram",
    "run_panel_items",
    "summarise_panel",
]

"""Scoring summary and the Day-1 go/no-go gate.

Gate on the 60-item dev set: Decider Q1 macro-F1 >= rule-baseline macro-F1 + 10 points AND the top
third of items by max(p_agg) has Q1 accuracy with a Wilson 95% lower bound >= 0.70. One condition
met is BORDERLINE (rewrite criteria once, rerun). The dev set is never reported as validation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cso.domain.enums import Nature, Response
from cso.evaluation.labels import GoldLabel
from cso.evaluation.runner import (
    ItemRun,
    SystemScore,
    ambiguous_rate,
    labelled_pairs,
    score_system,
)
from cso.evaluation.stats import (
    Proportion,
    ReliabilityBin,
    proportion,
    quantile,
    reliability_bins,
    top_fraction_accuracy,
)

REQUIRED_LABELS = 60
F1_MARGIN = 0.10
TOP_THIRD_LOWER_BOUND = 0.70
CANNOT_TELL_BELOW = 0.50
NATURES = tuple(n.value for n in Nature)
RESPONSES = tuple(r.value for r in Response)
RELIABILITY_EDGES = (0.0, 0.5, 0.8, 1.0)


def not_run_line(n_labelled: int) -> str:
    """The exact statement written when the spike cannot run."""
    return f"NOT RUN: insufficient labels ({n_labelled}/{REQUIRED_LABELS})"


@dataclass(frozen=True)
class Distribution:
    """Order-sensitivity distribution over scored items."""

    n: int
    p50: float | None
    p90: float | None
    maximum: float | None
    share_above_cap: Proportion


@dataclass(frozen=True)
class LatencySummary:
    """End-to-end and server-side request latency (ms)."""

    n: int
    p50: float | None
    p95: float | None
    server_p50: float | None
    server_p95: float | None


@dataclass(frozen=True)
class Summary:
    """Everything the spike and run reports need, computed on non-ambiguous labelled items."""

    n_labelled: int
    n_scored: int
    n_decider_failures: int
    ambiguous: Proportion
    q1_rules: SystemScore
    q1_k1: SystemScore
    q1_k3: SystemScore
    q2_rules: SystemScore
    q2_k1: SystemScore
    q2_k3: SystemScore
    top_third: Proportion
    cannot_tell_share: Proportion
    reliability: tuple[ReliabilityBin, ...]
    order_sensitivity: Distribution
    latency: LatencySummary


def summarise(
    runs: Sequence[ItemRun], gold: dict[int, GoldLabel], *, order_sensitivity_cap: float
) -> Summary:
    """Score all systems on the same items: labelled, non-ambiguous, Decider call succeeded."""
    pairs = labelled_pairs(runs, gold)
    decided = [(r, g) for r, g in pairs if r.error is None and r.k3_nature is not None]
    failures = sum(1 for r, _ in pairs if r.error is not None)
    scored = [(r, g) for r, g in decided if not g.ambiguous]

    truth_n = [g.nature for _, g in scored]
    truth_r = [g.response for _, g in scored]
    k1n = [r.k1_nature or "" for r, _ in scored]
    k3n = [r.k3_nature or "" for r, _ in scored]
    k1r = [r.k1_response or "" for r, _ in scored]
    k3r = [r.k3_response or "" for r, _ in scored]
    confidences = [r.max_p_nature or 0.0 for r, _ in scored]
    correct = [r.k3_nature == g.nature for r, g in scored]

    sensitivities = [r.order_sensitivity for r, _ in scored if r.order_sensitivity is not None]
    latencies = [float(r.latency_ms) for r, _ in decided if r.latency_ms is not None]
    server = [r.server_latency_ms for r, _ in decided if r.server_latency_ms is not None]
    return Summary(
        n_labelled=len(pairs),
        n_scored=len(scored),
        n_decider_failures=failures,
        ambiguous=ambiguous_rate(pairs),
        q1_rules=score_system(truth_n, [r.rules_nature for r, _ in scored], NATURES),
        q1_k1=score_system(truth_n, k1n, NATURES),
        q1_k3=score_system(truth_n, k3n, NATURES),
        q2_rules=score_system(truth_r, [r.rules_response for r, _ in scored], RESPONSES),
        q2_k1=score_system(truth_r, k1r, RESPONSES),
        q2_k3=score_system(truth_r, k3r, RESPONSES),
        top_third=top_fraction_accuracy(confidences, correct),
        cannot_tell_share=proportion(
            sum(1 for c in confidences if c < CANNOT_TELL_BELOW), len(scored)
        ),
        reliability=tuple(reliability_bins(confidences, correct, RELIABILITY_EDGES)),
        order_sensitivity=Distribution(
            n=len(sensitivities),
            p50=quantile(sensitivities, 0.5),
            p90=quantile(sensitivities, 0.9),
            maximum=max(sensitivities) if sensitivities else None,
            share_above_cap=proportion(
                sum(1 for s in sensitivities if s > order_sensitivity_cap), len(sensitivities)
            ),
        ),
        latency=LatencySummary(
            n=len(latencies),
            p50=quantile(latencies, 0.5),
            p95=quantile(latencies, 0.95),
            server_p50=quantile(server, 0.5),
            server_p95=quantile(server, 0.95),
        ),
    )


@dataclass(frozen=True)
class Gate:
    """The two gate conditions and the resulting verdict."""

    f1_delta: float
    f1_condition: bool
    top_third_lower: float
    top_third_condition: bool
    verdict: str  # GO | BORDERLINE | NO-GO


def evaluate_gate(summary: Summary) -> Gate:
    """Apply the section 2 gate to a summary (Decider K=3 against the rule baseline)."""
    delta = summary.q1_k3.macro_f1 - summary.q1_rules.macro_f1
    f1_ok = delta >= F1_MARGIN - 1e-12
    top_ok = summary.top_third.n > 0 and summary.top_third.lower >= TOP_THIRD_LOWER_BOUND
    met = int(f1_ok) + int(top_ok)
    verdict = "GO" if met == 2 else "BORDERLINE" if met == 1 else "NO-GO"
    return Gate(delta, f1_ok, summary.top_third.lower, top_ok, verdict)


def verdict_line(gate: Gate) -> str:
    """One-line verdict."""
    if gate.verdict == "BORDERLINE":
        return (
            "VERDICT: BORDERLINE (one of two conditions met): rewrite the criteria once and rerun"
        )
    return f"VERDICT: {gate.verdict}"

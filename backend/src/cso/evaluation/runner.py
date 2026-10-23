"""Run the compared systems over a set of changesets and score them against gold labels.

Systems (identical evidence text and option sets): the rule baseline, Decider K=1 (the first
option order only) and Decider K=3 (the shuffle-averaged product configuration). K=1 and K=3
come from the same single Decider request, so they see exactly the same state.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from cso.adapters.decider import DeciderClient, DeciderError
from cso.domain.config import CommunityConfig
from cso.domain.evidence import render
from cso.domain.models import DecisionOutputs, EvidenceSnapshot
from cso.evaluation.baselines import rule_baseline
from cso.evaluation.labels import AMBIGUOUS, GoldLabel
from cso.evaluation.paths import write_text_lf
from cso.evaluation.stats import (
    ClassScore,
    Proportion,
    accuracy,
    macro_f1,
    per_class_scores,
    proportion,
)

SnapshotProvider = Callable[[int], Awaitable[EvidenceSnapshot]]


@dataclass(frozen=True)
class ItemRun:
    """All systems' answers for one changeset (decider fields are None when the call failed)."""

    changeset_id: int
    rules_nature: str
    rules_response: str
    rules_fired: tuple[str, ...]
    k1_nature: str | None = None
    k1_response: str | None = None
    k3_nature: str | None = None
    k3_response: str | None = None
    max_p_nature: float | None = None
    order_sensitivity: float | None = None
    latency_ms: int | None = None
    server_latency_ms: float | None = None
    error: str | None = None


def _top(probabilities: dict[str, float]) -> str:
    """Argmax with ties going to the earlier key (the base option order)."""
    best = max(probabilities.values())
    return next(k for k, v in probabilities.items() if v >= best - 1e-12)


def k1_k3(outputs: DecisionOutputs) -> tuple[str, str, str, str]:
    """(K=1 nature, K=1 response, K=3 nature, K=3 response); K=1 is permutation 0 only."""
    by_name = {p.name: p for p in outputs.permutations}
    return (
        _top(by_name["nature_p0"].probabilities),
        _top(by_name["response_p0"].probabilities),
        outputs.nature.argmax,
        outputs.response.argmax,
    )


async def run_items(
    ids: Sequence[int],
    snapshots: SnapshotProvider,
    config: CommunityConfig,
    decider: DeciderClient | None,
    *,
    receipts_dir: Path | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
) -> list[ItemRun]:
    """Run the rule baseline (always) and the Decider (when a client is given) per changeset.

    A Decider failure is recorded on the item (`error`) and never replaced by a default answer.
    Every successful Decider result is written to `receipts_dir/<changeset>.json`.
    """
    runs: list[ItemRun] = []
    for n, cs in enumerate(ids, start=1):
        snapshot = await snapshots(cs)
        rules = rule_baseline(snapshot, config)
        base = ItemRun(
            changeset_id=cs,
            rules_nature=rules.nature.value,
            rules_response=rules.response.value,
            rules_fired=rules.fired,
        )
        if decider is None:
            runs.append(base)
            continue
        rendered = render(snapshot, config)
        try:
            result = await decider.decide(rendered.text, config)
        except DeciderError as exc:
            runs.append(replace(base, error=f"{type(exc).__name__}: {str(exc)[:200]}"))
            progress(f"[{n}/{len(ids)}] {cs}: decider error {type(exc).__name__}")
            continue
        k1n, k1r, k3n, k3r = k1_k3(result.outputs)
        runs.append(
            replace(
                base,
                k1_nature=k1n,
                k1_response=k1r,
                k3_nature=k3n,
                k3_response=k3r,
                max_p_nature=max(result.outputs.nature.probabilities.values()),
                order_sensitivity=result.outputs.nature.order_sensitivity,
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
                        "rendered_tokens_estimate": rendered.estimated_tokens,
                        "questions_hash": result.questions_hash,
                        "identity": result.identity.model_dump(mode="json"),
                        "outputs": result.outputs.model_dump(mode="json"),
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


@dataclass(frozen=True)
class SystemScore:
    """Accuracy and macro-F1 of one system on one question (ambiguous items already excluded)."""

    n: int
    macro_f1: float
    accuracy: Proportion
    per_class: tuple[ClassScore, ...]


def score_system(
    y_true: Sequence[str], y_pred: Sequence[str], classes: Sequence[str]
) -> SystemScore:
    """Score predictions; every proportion carries a Wilson 95% interval."""
    return SystemScore(
        n=len(y_true),
        macro_f1=macro_f1(y_true, y_pred, classes),
        accuracy=accuracy(y_true, y_pred),
        per_class=tuple(per_class_scores(y_true, y_pred, classes)),
    )


def labelled_pairs(
    runs: Sequence[ItemRun], gold: dict[int, GoldLabel]
) -> list[tuple[ItemRun, GoldLabel]]:
    """Runs that have a gold label, in run order."""
    return [(r, gold[r.changeset_id]) for r in runs if r.changeset_id in gold]


def ambiguous_rate(pairs: Sequence[tuple[ItemRun, GoldLabel]]) -> Proportion:
    """Share of labelled items adjudicated `ambiguous`."""
    return proportion(sum(1 for _, g in pairs if g.nature == AMBIGUOUS), len(pairs))

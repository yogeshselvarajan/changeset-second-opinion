"""Average permutations per question and assemble the domain's DecisionOutputs.

Averaging reduces order-induced variance; it does not recalibrate. `confidence_agg` measures how
decisive the averaged output is, not how likely the chosen option is correct.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations

from cso.adapters.decider.questions import RequestPlan
from cso.adapters.decider.validate import ValidatedResponse
from cso.domain.models import AggregatedChoice, DecisionOutputs, PermutationResult


def aggregate_choice(
    permutations: Sequence[PermutationResult], option_order: Sequence[str]
) -> AggregatedChoice:
    """Mean per option; argmax from the mean (ties go to the earlier base option).

    `order_sensitivity` is the largest pairwise L1 distance between permutation vectors (0 to 2).
    `confidence_agg` is (N * max(p_agg) - 1) / (N - 1), clamped to [0, 1].
    """
    n = len(option_order)
    if not permutations:
        raise ValueError("at least one permutation is required")
    if n < 2:
        raise ValueError("a choice needs at least two options")
    for perm in permutations:
        if set(perm.probabilities) != set(option_order):
            raise ValueError("permutation options differ from the question options")
    k = len(permutations)
    mean = {o: min(1.0, sum(p.probabilities[o] for p in permutations) / k) for o in option_order}
    top = max(mean.values())
    argmax = next(o for o in option_order if mean[o] >= top - 1e-12)
    sensitivity = max(
        (
            sum(abs(a.probabilities[o] - b.probabilities[o]) for o in option_order)
            for a, b in combinations(permutations, 2)
        ),
        default=0.0,
    )
    confidence = min(1.0, max(0.0, (n * top - 1) / (n - 1)))
    return AggregatedChoice(
        probabilities=mean,
        argmax=argmax,
        confidence_agg=confidence,
        order_sensitivity=sensitivity,
    )


def assemble_outputs(
    plan: RequestPlan, validated: ValidatedResponse, option_orders: dict[str, list[str]]
) -> DecisionOutputs:
    """Turn a validated response into per-permutation results and aggregated Q1/Q2.

    `option_orders` maps `nature`/`response` to the base option order of the config.
    """
    permutations = [
        PermutationResult(
            name=name,
            order=list(order),
            probabilities=validated.choices[name].probabilities,
            confidence=validated.choices[name].confidence,
        )
        for name, order in plan.orders.items()
    ]
    by_name = {p.name: p for p in permutations}

    def group(key: str) -> AggregatedChoice:
        return aggregate_choice([by_name[n] for n in plan.groups[key]], option_orders[key])

    return DecisionOutputs(
        permutations=permutations,
        nature=group("nature"),
        response=group("response"),
        nouls=dict(validated.nouls),
    )

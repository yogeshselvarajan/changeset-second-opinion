"""Average permutations, measure order sensitivity and assign a band.

Averaging reduces order-induced variance; it does not recalibrate. `confidence_agg` measures how
decisive the averaged output is, not how likely the chosen option is correct.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class Aggregate:
    """Mean probabilities of one question over its permutations, plus sharpness statistics."""

    probabilities: dict[str, float]
    argmax: str
    confidence_agg: float
    order_sensitivity: float


def aggregate(
    permutations: Sequence[Mapping[str, float]], option_order: Sequence[str]
) -> Aggregate:
    """Mean per option; argmax from the mean (ties go to the earlier base option).

    `order_sensitivity` is the largest pairwise L1 distance between permutation vectors (0 to 2).
    `confidence_agg` is (N * max(p_agg) - 1) / (N - 1), clamped to [0, 1].
    """
    if not permutations:
        raise ValueError("at least one permutation is required")
    n = len(option_order)
    if n < 2:
        raise ValueError("a choice needs at least two options")
    for perm in permutations:
        if set(perm) != set(option_order):
            raise ValueError("permutation options differ from the question options")
    k = len(permutations)
    mean = {o: sum(p[o] for p in permutations) / k for o in option_order}
    top = max(mean.values())
    argmax = next(o for o in option_order if mean[o] >= top - 1e-12)
    sensitivity = max(
        (sum(abs(a[o] - b[o]) for o in option_order) for a, b in combinations(permutations, 2)),
        default=0.0,
    )
    confidence = min(1.0, max(0.0, (n * top - 1) / (n - 1)))
    return Aggregate(mean, argmax, confidence, sensitivity)


def band(
    max_probability: float,
    order_sensitivity: float,
    *,
    confident_min: float = 0.80,
    unsure_min: float = 0.50,
    order_sensitivity_max: float = 0.30,
) -> str:
    """`confident`, `unsure` or `cannot_tell`; large order sensitivity forces `cannot_tell`."""
    if order_sensitivity > order_sensitivity_max:
        return "cannot_tell"
    if max_probability >= confident_min:
        return "confident"
    if max_probability >= unsure_min:
        return "unsure"
    return "cannot_tell"

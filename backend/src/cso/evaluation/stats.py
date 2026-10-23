"""Small, dependency-free statistics for the evaluation harness.

Every proportion reported by the harness carries a Wilson 95% interval (`wilson_interval`).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Proportion:
    """k successes out of n with its Wilson 95% interval (n = 0 gives the vacuous [0, 1])."""

    k: int
    n: int
    lower: float
    upper: float

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n < 0 or k < 0 or k > n:
        raise ValueError("require 0 <= k <= n")
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion(k: int, n: int) -> Proportion:
    """Build a `Proportion` with its Wilson interval."""
    lower, upper = wilson_interval(k, n)
    return Proportion(k=k, n=n, lower=lower, upper=upper)


@dataclass(frozen=True)
class ClassScore:
    """Precision, recall and F1 of one class, with intervals on precision and recall."""

    label: str
    support: int
    predicted: int
    true_positive: int
    precision: Proportion
    recall: Proportion
    f1: float


def per_class_scores(
    y_true: Sequence[str], y_pred: Sequence[str], classes: Sequence[str]
) -> list[ClassScore]:
    """One `ClassScore` per class in `classes`."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred differ in length")
    scores: list[ClassScore] = []
    for label in classes:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p == label)
        support = sum(1 for t in y_true if t == label)
        predicted = sum(1 for p in y_pred if p == label)
        precision = proportion(tp, predicted)
        recall = proportion(tp, support)
        denominator = predicted + support
        f1 = 2 * tp / denominator if denominator else 0.0
        scores.append(ClassScore(label, support, predicted, tp, precision, recall, f1))
    return scores


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str], classes: Sequence[str]) -> float:
    """Unweighted mean F1 over the classes that occur in `y_true` (support > 0).

    Classes with no true examples are excluded so an absent class cannot dilute or inflate the
    score; per-class support is reported alongside every macro-F1.
    """
    scores = [s for s in per_class_scores(y_true, y_pred, classes) if s.support > 0]
    return sum(s.f1 for s in scores) / len(scores) if scores else 0.0


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> Proportion:
    """Share of exact matches with its Wilson interval."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred differ in length")
    return proportion(sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p), len(y_true))


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float | None:
    """Cohen's kappa between two raters; None when chance agreement is 1 or there is no data."""
    if len(a) != len(b):
        raise ValueError("rating lists differ in length")
    n = len(a)
    if n == 0:
        return None
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[label] * cb[label] for label in set(ca) | set(cb)) / (n * n)
    if math.isclose(expected, 1.0):
        return None
    return (observed - expected) / (1 - expected)


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation quantile (q in [0, 1]); None for no data."""
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be within [0, 1]")
    if not values:
        return None
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


@dataclass(frozen=True)
class ReliabilityBin:
    """Accuracy among items whose top probability falls in [lo, hi) (last bin closed)."""

    lo: float
    hi: float
    accuracy: Proportion


def reliability_bins(
    confidences: Sequence[float], correct: Sequence[bool], edges: Sequence[float]
) -> list[ReliabilityBin]:
    """Bin items by `confidences` using ascending `edges`; every bin reports n and a Wilson CI."""
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct differ in length")
    if len(edges) < 2 or list(edges) != sorted(edges):
        raise ValueError("edges must be ascending with at least two values")
    bins: list[ReliabilityBin] = []
    last = len(edges) - 2
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        members = [
            ok
            for c, ok in zip(confidences, correct, strict=True)
            if (lo <= c < hi) or (i == last and c == hi)
        ]
        bins.append(ReliabilityBin(lo, hi, proportion(sum(members), len(members))))
    return bins


def top_fraction_accuracy(
    confidences: Sequence[float], correct: Sequence[bool], fraction: float = 1 / 3
) -> Proportion:
    """Accuracy among the `ceil(fraction * n)` items with the highest confidence.

    Ties at the cut are broken by input order (stable), which keeps the result deterministic.
    """
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct differ in length")
    n = len(confidences)
    if n == 0:
        return proportion(0, 0)
    take = max(1, math.ceil(fraction * n))
    order = sorted(range(n), key=lambda i: -confidences[i])[:take]
    return proportion(sum(1 for i in order if correct[i]), len(order))

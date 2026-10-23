from __future__ import annotations

import pytest

from cso.evaluation.stats import (
    accuracy,
    cohen_kappa,
    macro_f1,
    per_class_scores,
    proportion,
    quantile,
    reliability_bins,
    top_fraction_accuracy,
    wilson_interval,
)


@pytest.mark.parametrize(
    ("k", "n", "lower", "upper"),
    [
        (0, 10, 0.0, 0.2775),
        (5, 10, 0.2366, 0.7634),
        (10, 10, 0.7225, 1.0),
        (90, 120, 0.6656, 0.8189),
        (8, 10, 0.4902, 0.9433),
    ],
)
def test_wilson_interval_matches_reference_values(
    k: int, n: int, lower: float, upper: float
) -> None:
    lo, hi = wilson_interval(k, n)
    assert lo == pytest.approx(lower, abs=1e-4)
    assert hi == pytest.approx(upper, abs=1e-4)


def test_wilson_is_vacuous_without_data_and_rejects_bad_counts() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(3, 2)
    with pytest.raises(ValueError):
        wilson_interval(-1, 2)


def test_proportion_value_and_bounds() -> None:
    p = proportion(3, 12)
    assert p.value == 0.25
    assert 0.0 <= p.lower < 0.25 < p.upper <= 1.0
    assert proportion(0, 0).value is None


def test_macro_f1_perfect_and_known_mixed_case() -> None:
    classes = ["a", "b", "c"]
    assert macro_f1(["a", "b", "c"], ["a", "b", "c"], classes) == 1.0
    # a: tp1 fp0 fn1 -> f1 2/3; b: tp1 fp1 fn0 -> f1 2/3; c: tp0 fp0 fn0 (no support: excluded)
    assert macro_f1(["a", "a", "b"], ["a", "b", "b"], classes) == pytest.approx(2 / 3)


def test_macro_f1_ignores_classes_without_support_but_penalises_false_positives() -> None:
    classes = ["a", "b"]
    # b never occurs in truth: it is excluded, yet its false positives lower a's recall.
    assert macro_f1(["a", "a"], ["a", "b"], classes) == pytest.approx(2 / 3)
    assert macro_f1([], [], classes) == 0.0


def test_per_class_scores_carry_intervals() -> None:
    scores = per_class_scores(["a", "a", "b"], ["a", "b", "b"], ["a", "b"])
    a = scores[0]
    assert (a.support, a.predicted, a.true_positive) == (2, 1, 1)
    assert a.precision.n == 1 and a.recall.n == 2
    assert a.recall.lower < 0.5 < a.recall.upper


def test_accuracy_has_wilson_interval() -> None:
    acc = accuracy(["a", "b", "a", "a"], ["a", "b", "b", "a"])
    assert (acc.k, acc.n) == (3, 4)
    assert acc.lower < 0.75 < acc.upper


def test_cohen_kappa_known_values() -> None:
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["b", "b", "a", "a"]) == -1.0
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["a", "a"], ["a", "a"]) is None  # chance agreement is 1


def test_quantile_interpolates() -> None:
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([10.0], 0.95) == 10.0
    assert quantile([], 0.5) is None
    assert quantile([1, 2, 3, 4, 5], 1.0) == 5
    with pytest.raises(ValueError):
        quantile([1], 1.5)


def test_reliability_bins_report_n_per_bin() -> None:
    bins = reliability_bins(
        [0.1, 0.4, 0.6, 0.7, 0.9, 1.0], [False, True, True, False, True, True], [0.0, 0.5, 0.8, 1.0]
    )
    assert [b.accuracy.n for b in bins] == [2, 2, 2]
    assert [b.accuracy.k for b in bins] == [1, 1, 2]


def test_top_fraction_accuracy_uses_most_confident_items() -> None:
    conf = [0.9, 0.2, 0.8, 0.1, 0.7, 0.3]
    ok = [True, False, True, False, False, False]
    top = top_fraction_accuracy(conf, ok)  # ceil(6/3) = 2 items: 0.9 and 0.8
    assert (top.k, top.n) == (2, 2)
    assert top_fraction_accuracy([], []).n == 0

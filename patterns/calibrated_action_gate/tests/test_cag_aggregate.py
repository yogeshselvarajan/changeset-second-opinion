from __future__ import annotations

import pytest

from calibrated_action_gate import aggregate, band, reconcile

OPTS = ["a", "b", "c", "d"]


def vec(a: float, b: float, c: float, d: float) -> dict[str, float]:
    return {"a": a, "b": b, "c": c, "d": d}


def test_identical_permutations_have_zero_sensitivity() -> None:
    p = vec(0.4, 0.3, 0.2, 0.1)
    agg = aggregate([p, p, p], OPTS)
    assert agg.order_sensitivity == 0
    assert agg.probabilities == pytest.approx(p)
    assert agg.argmax == "a"


def test_disagreeing_permutations_have_positive_sensitivity_and_argmax_from_the_mean() -> None:
    perms = [vec(0.7, 0.1, 0.1, 0.1), vec(0.1, 0.5, 0.2, 0.2), vec(0.1, 0.5, 0.2, 0.2)]
    agg = aggregate(perms, OPTS)
    assert agg.order_sensitivity == pytest.approx(1.2)  # L1(p0, p1) = 0.6+0.4+0.1+0.1
    assert agg.probabilities["b"] == pytest.approx(0.3667, abs=1e-4)
    assert agg.argmax == "b"  # a wins one permutation but loses on the mean


def test_confidence_agg_rescales_from_the_uniform_floor() -> None:
    uniform = aggregate([vec(0.25, 0.25, 0.25, 0.25)], OPTS)
    assert uniform.confidence_agg == pytest.approx(0)
    sure = aggregate([vec(1, 0, 0, 0)], OPTS)
    assert sure.confidence_agg == pytest.approx(1)
    mid = aggregate([vec(0.5, 0.2, 0.2, 0.1)], OPTS)
    assert mid.confidence_agg == pytest.approx((4 * 0.5 - 1) / 3)


def test_ties_go_to_the_earlier_base_option_and_single_permutation_has_no_sensitivity() -> None:
    agg = aggregate([vec(0.1, 0.4, 0.4, 0.1)], OPTS)
    assert agg.argmax == "b"
    assert agg.order_sensitivity == 0


def test_mismatched_options_are_rejected() -> None:
    with pytest.raises(ValueError):
        aggregate([{"a": 1.0, "z": 0.0}], ["a", "b"])
    with pytest.raises(ValueError):
        aggregate([], OPTS)


@pytest.mark.parametrize(
    ("p", "sensitivity", "expected"),
    [
        (0.9, 0.0, "confident"),
        (0.8, 0.0, "confident"),
        (0.79, 0.0, "unsure"),
        (0.5, 0.0, "unsure"),
        (0.49, 0.0, "cannot_tell"),
        (0.95, 0.31, "cannot_tell"),  # order sensitivity forces cannot_tell
        (0.95, 0.30, "confident"),
    ],
)
def test_band(p: float, sensitivity: float, expected: str) -> None:
    assert band(p, sensitivity) == expected


def test_reconcile_keeps_an_allowed_response() -> None:
    probs = {
        "no_action_suggested": 0.6,
        "welcome_and_tips": 0.2,
        "ask_source_question": 0.1,
        "request_local_check": 0.05,
        "escalate_to_experienced_reviewer": 0.05,
    }
    r = reconcile("consistent_edit", probs)
    assert (r.response, r.reconciled, r.original) == (
        "no_action_suggested",
        False,
        "no_action_suggested",
    )


def test_reconcile_replaces_a_disallowed_response_with_the_best_allowed_one() -> None:
    probs = {
        "no_action_suggested": 0.1,
        "welcome_and_tips": 0.05,
        "ask_source_question": 0.2,
        "request_local_check": 0.15,
        "escalate_to_experienced_reviewer": 0.5,
    }
    r = reconcile("needs_local_knowledge", probs)
    assert r.reconciled is True
    assert r.original == "escalate_to_experienced_reviewer"
    assert r.response == "ask_source_question"

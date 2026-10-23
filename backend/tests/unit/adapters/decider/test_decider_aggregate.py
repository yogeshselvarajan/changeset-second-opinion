from __future__ import annotations

import pytest
from decider_support import config, recorded_response

from cso.adapters.decider import aggregate_choice, assemble_outputs, build_plan, validate_response
from cso.domain.models import PermutationResult

OPTS = ["a", "b", "c", "d"]


def perm(name: str, a: float, b: float, c: float, d: float) -> PermutationResult:
    return PermutationResult(
        name=name, order=OPTS, probabilities={"a": a, "b": b, "c": c, "d": d}, confidence=0.1
    )


def test_identical_permutations_have_zero_sensitivity() -> None:
    p = [perm(f"q_p{i}", 0.4, 0.3, 0.2, 0.1) for i in range(3)]
    agg = aggregate_choice(p, OPTS)
    assert agg.order_sensitivity == 0
    assert agg.argmax == "a"
    assert agg.probabilities == pytest.approx({"a": 0.4, "b": 0.3, "c": 0.2, "d": 0.1})


def test_disagreeing_permutations_have_sensitivity_and_argmax_from_the_mean() -> None:
    p = [
        perm("q_p0", 0.7, 0.1, 0.1, 0.1),
        perm("q_p1", 0.1, 0.5, 0.2, 0.2),
        perm("q_p2", 0.1, 0.5, 0.2, 0.2),
    ]
    agg = aggregate_choice(p, OPTS)
    assert agg.order_sensitivity == pytest.approx(1.2)
    assert agg.argmax == "b"  # a wins one permutation but loses on the mean


def test_confidence_agg_rescales_from_the_uniform_floor() -> None:
    assert aggregate_choice([perm("p", 0.25, 0.25, 0.25, 0.25)], OPTS).confidence_agg == 0
    assert aggregate_choice([perm("p", 1, 0, 0, 0)], OPTS).confidence_agg == 1
    mid = aggregate_choice([perm("p", 0.5, 0.2, 0.2, 0.1)], OPTS)
    assert mid.confidence_agg == pytest.approx((4 * 0.5 - 1) / 3)


def test_ties_go_to_the_earlier_base_option() -> None:
    assert aggregate_choice([perm("p", 0.1, 0.4, 0.4, 0.1)], OPTS).argmax == "b"


def test_mismatched_options_and_empty_input_are_rejected() -> None:
    with pytest.raises(ValueError):
        aggregate_choice([perm("p", 0.25, 0.25, 0.25, 0.25)], ["a", "b"])
    with pytest.raises(ValueError):
        aggregate_choice([], OPTS)


def test_assembled_outputs_from_the_recorded_response_keep_every_permutation() -> None:
    cfg = config()
    plan = build_plan("state", cfg)
    out = assemble_outputs(
        plan,
        validate_response(recorded_response(), plan),
        {
            "nature": [o.code for o in cfg.option_sets.nature],
            "response": [o.code for o in cfg.option_sets.response],
        },
    )
    assert [p.name for p in out.permutations] == list(plan.orders)
    assert all(p.order == list(plan.orders[p.name]) for p in out.permutations)
    assert list(out.nature.probabilities) == [o.code for o in cfg.option_sets.nature]
    assert out.nature.argmax in out.nature.probabilities
    assert set(out.nouls) == set(plan.nouls)
    assert 0 <= out.nature.confidence_agg <= 1

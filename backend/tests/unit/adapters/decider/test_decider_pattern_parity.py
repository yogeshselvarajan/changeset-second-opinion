"""The backend adapter and the standalone pattern package must agree on the same recorded data."""

from __future__ import annotations

import importlib
import sys

import pytest
from decider_support import PATTERN_SRC, config, recorded_request, recorded_response

from cso.adapters.decider import assemble_outputs, build_plan, validate_response


@pytest.fixture(scope="module")
def pattern():  # type: ignore[no-untyped-def]
    sys.path.insert(0, str(PATTERN_SRC))
    try:
        yield importlib.import_module("calibrated_action_gate")
    finally:
        sys.path.remove(str(PATTERN_SRC))
        for name in [m for m in sys.modules if m.startswith("calibrated_action_gate")]:
            del sys.modules[name]


def test_same_request_and_hash(pattern) -> None:  # type: ignore[no-untyped-def]
    cfg = config()
    ours = build_plan(recorded_request()["state"], cfg)
    q = recorded_request()["questions"]
    theirs = pattern.build_request(
        recorded_request()["state"],
        [
            pattern.ChoiceSpec(
                "nature", q["nature_p0"]["instructions"], q["nature_p0"]["criteria"]
            ),
            pattern.ChoiceSpec(
                "response", q["response_p0"]["instructions"], q["response_p0"]["criteria"]
            ),
        ],
        [pattern.NoulSpec(n, q[n]["instructions"]) for n in ours.nouls],
    )
    assert ours.request == theirs.request == recorded_request()
    assert ours.questions_hash == theirs.questions_hash
    assert ours.orders == theirs.orders


def test_same_aggregates_and_nouls(pattern) -> None:  # type: ignore[no-untyped-def]
    cfg = config()
    plan = build_plan("s", cfg)
    validated = validate_response(recorded_response(), plan)
    orders = {
        "nature": [o.code for o in cfg.option_sets.nature],
        "response": [o.code for o in cfg.option_sets.response],
    }
    ours = assemble_outputs(plan, validated, orders)

    q = recorded_request()["questions"]
    specs = [
        pattern.ChoiceSpec("nature", q["nature_p0"]["instructions"], q["nature_p0"]["criteria"]),
        pattern.ChoiceSpec(
            "response", q["response_p0"]["instructions"], q["response_p0"]["criteria"]
        ),
    ]
    nouls = [pattern.NoulSpec(n, q[n]["instructions"]) for n in plan.nouls]
    pplan = pattern.build_request("s", specs, nouls)
    pvalid = pattern.validate_response(recorded_response(), pplan)
    for key, mine in (("nature", ours.nature), ("response", ours.response)):
        agg = pattern.aggregate(
            [pvalid.choices[n].probabilities for n in pplan.groups[key]], orders[key]
        )
        assert agg.argmax == mine.argmax
        assert agg.order_sensitivity == pytest.approx(mine.order_sensitivity)
        assert agg.confidence_agg == pytest.approx(mine.confidence_agg)
        assert agg.probabilities == pytest.approx(mine.probabilities)
    assert pvalid.nouls == pytest.approx(ours.nouls)

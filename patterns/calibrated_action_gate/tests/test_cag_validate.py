from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from calibrated_action_gate import RequestPlan, SchemaError, validate_response


def test_the_recorded_real_response_validates(
    plan: RequestPlan, recorded_response: dict[str, Any]
) -> None:
    v = validate_response(recorded_response, plan)
    assert v.model == "strands-decider-2B-qwen3.5-v1-2610"
    assert set(v.choices) == set(plan.orders)
    assert set(v.nouls) == set(plan.nouls)
    assert v.input_tokens == recorded_response["usage"]["input_tokens"] > 0
    assert v.server_latency_ms == recorded_response["latency_ms"]


def _drop_option(r: dict[str, Any]) -> None:
    del r["answers"]["nature_p0"]["probabilities"]["needs_local_knowledge"]


def _extra_option(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["probabilities"]["bonus"] = 0.0


def _sum_not_one(r: dict[str, Any]) -> None:
    probs = r["answers"]["nature_p1"]["probabilities"]
    probs["consistent_edit"] = round(probs["consistent_edit"] * 0.5, 4)


def _wrong_argmax(r: dict[str, Any]) -> None:
    a = r["answers"]["response_p0"]
    a["choice"] = min(a["probabilities"], key=lambda k: a["probabilities"][k])


def _confidence_high(r: dict[str, Any]) -> None:
    r["answers"]["nature_p2"]["confidence"] = 1.2


def _confidence_negative(r: dict[str, Any]) -> None:
    r["answers"]["nature_p2"]["confidence"] = -0.01


def _noul_high(r: dict[str, Any]) -> None:
    r["answers"]["comment_matches_changes"]["noul"] = 1.5


def _noul_negative(r: dict[str, Any]) -> None:
    r["answers"]["mature_feature_deleted_probe"]["noul"] = -0.2


def _noul_wrong_key(r: dict[str, Any]) -> None:
    a = r["answers"]["comment_matches_changes"]
    a["value"] = a.pop("noul")


def _missing_answer(r: dict[str, Any]) -> None:
    del r["answers"]["response_p2"]


def _extra_answer(r: dict[str, Any]) -> None:
    r["answers"]["surprise"] = {"type": "noul", "noul": 0.5}


def _wrong_type(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["type"] = "noul"


def _choice_not_an_option(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["choice"] = "something_else"


def _nan_probability(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["probabilities"]["consistent_edit"] = float("nan")


def _bool_probability(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["probabilities"]["consistent_edit"] = True


def _string_probability(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["probabilities"]["consistent_edit"] = "0.5"


def _negative_probability(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["probabilities"]["consistent_edit"] = -0.1


def _extra_answer_field(r: dict[str, Any]) -> None:
    r["answers"]["nature_p0"]["rationale"] = "because"


def _missing_confidence(r: dict[str, Any]) -> None:
    del r["answers"]["nature_p0"]["confidence"]


def _missing_usage(r: dict[str, Any]) -> None:
    del r["usage"]


def _negative_tokens(r: dict[str, Any]) -> None:
    r["usage"]["input_tokens"] = -1


def _unknown_top_level(r: dict[str, Any]) -> None:
    r["extra"] = 1


def _empty_model(r: dict[str, Any]) -> None:
    r["model"] = ""


def _answers_list(r: dict[str, Any]) -> None:
    r["answers"] = list(r["answers"].values())


FUZZ: list[Callable[[dict[str, Any]], None]] = [
    _drop_option,
    _extra_option,
    _sum_not_one,
    _wrong_argmax,
    _confidence_high,
    _confidence_negative,
    _noul_high,
    _noul_negative,
    _noul_wrong_key,
    _missing_answer,
    _extra_answer,
    _wrong_type,
    _choice_not_an_option,
    _nan_probability,
    _bool_probability,
    _string_probability,
    _negative_probability,
    _extra_answer_field,
    _missing_confidence,
    _missing_usage,
    _negative_tokens,
    _unknown_top_level,
    _empty_model,
    _answers_list,
]


@pytest.mark.parametrize("mutate", FUZZ, ids=lambda f: f.__name__.lstrip("_"))
def test_every_deviation_is_rejected_and_the_raw_response_is_kept(
    plan: RequestPlan, mutable_response: dict[str, Any], mutate: Callable[[dict[str, Any]], None]
) -> None:
    mutate(mutable_response)
    snapshot = copy.deepcopy(mutable_response)
    with pytest.raises(SchemaError) as info:
        validate_response(mutable_response, plan)
    assert info.value.raw is not None
    assert info.value.reason
    assert mutable_response == snapshot  # validation never repairs the response


@pytest.mark.parametrize("raw", [None, [], "text", 3, {}])
def test_non_object_or_empty_responses_are_rejected(plan: RequestPlan, raw: object) -> None:
    with pytest.raises(SchemaError):
        validate_response(raw, plan)


def test_tiny_rounding_in_the_sum_is_tolerated(
    plan: RequestPlan, mutable_response: dict[str, Any]
) -> None:
    probs = mutable_response["answers"]["nature_p0"]["probabilities"]
    top = max(probs, key=lambda k: probs[k])
    probs[top] = round(probs[top] + 0.0008, 4)
    validate_response(mutable_response, plan)


def test_latency_is_optional(plan: RequestPlan, mutable_response: dict[str, Any]) -> None:
    del mutable_response["latency_ms"]
    assert validate_response(mutable_response, plan).server_latency_ms is None

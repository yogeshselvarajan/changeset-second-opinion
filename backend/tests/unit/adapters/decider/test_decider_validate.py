from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from decider_support import config, recorded_response

from cso.adapters.decider import DeciderSchemaError, build_plan, validate_response

Mutation = Callable[[dict[str, Any]], None]


def _nature(r: dict[str, Any], p: str = "nature_p0") -> dict[str, Any]:
    return r["answers"][p]  # type: ignore[no-any-return]


def _set(path: str, key: str, value: Any) -> Mutation:
    def apply(r: dict[str, Any]) -> None:
        r["answers"][path][key] = value

    return apply


def _drop_option(r: dict[str, Any]) -> None:
    del _nature(r)["probabilities"]["needs_local_knowledge"]


def _extra_option(r: dict[str, Any]) -> None:
    _nature(r)["probabilities"]["bonus"] = 0.0


def _sum_not_one(r: dict[str, Any]) -> None:
    probs = _nature(r, "nature_p1")["probabilities"]
    probs["consistent_edit"] = round(probs["consistent_edit"] * 0.5, 4)


def _wrong_argmax(r: dict[str, Any]) -> None:
    a = _nature(r, "response_p0")
    a["choice"] = min(a["probabilities"], key=lambda k: a["probabilities"][k])


def _noul_wrong_key(r: dict[str, Any]) -> None:
    a = r["answers"]["comment_matches_changes"]
    a["value"] = a.pop("noul")


def _missing_answer(r: dict[str, Any]) -> None:
    del r["answers"]["response_p2"]


def _extra_answer(r: dict[str, Any]) -> None:
    r["answers"]["surprise"] = {"type": "noul", "noul": 0.5}


def _missing_usage(r: dict[str, Any]) -> None:
    del r["usage"]


def _prob(option: str, value: Any) -> Mutation:
    def apply(r: dict[str, Any]) -> None:
        _nature(r)["probabilities"][option] = value

    return apply


FUZZ: dict[str, Mutation] = {
    "missing_option": _drop_option,
    "extra_option": _extra_option,
    "sum_not_one": _sum_not_one,
    "wrong_argmax": _wrong_argmax,
    "confidence_above_one": _set("nature_p2", "confidence", 1.2),
    "confidence_negative": _set("nature_p2", "confidence", -0.01),
    "confidence_not_a_number": _set("nature_p2", "confidence", "high"),
    "noul_above_one": _set("comment_matches_changes", "noul", 1.5),
    "noul_negative": _set("mature_feature_deleted_probe", "noul", -0.2),
    "noul_wrong_key": _noul_wrong_key,
    "answer_missing": _missing_answer,
    "answer_extra": _extra_answer,
    "wrong_type": _set("nature_p0", "type", "noul"),
    "choice_not_an_option": _set("nature_p0", "choice", "something_else"),
    "probability_nan": _prob("consistent_edit", float("nan")),
    "probability_bool": _prob("consistent_edit", True),
    "probability_string": _prob("consistent_edit", "0.5"),
    "probability_negative": _prob("consistent_edit", -0.1),
    "answer_field_extra": _set("nature_p0", "rationale", "because"),
    "usage_missing": _missing_usage,
    "tokens_negative": lambda r: r["usage"].__setitem__("input_tokens", -1),
    "top_level_unknown": lambda r: r.__setitem__("extra", 1),
    "model_empty": lambda r: r.__setitem__("model", ""),
    "answers_is_list": lambda r: r.__setitem__("answers", list(r["answers"].values())),
}


def test_the_recorded_real_response_validates() -> None:
    plan = build_plan("state", config())
    v = validate_response(recorded_response(), plan)
    assert set(v.choices) == set(plan.orders)
    assert set(v.nouls) == set(plan.nouls)
    assert v.input_tokens > 0
    assert v.server_latency_ms is not None


@pytest.mark.parametrize("name", FUZZ)
def test_every_deviation_is_rejected_with_the_raw_response_attached(name: str) -> None:
    plan = build_plan("state", config())
    response = recorded_response()
    FUZZ[name](response)
    before = copy.deepcopy(response)
    with pytest.raises(DeciderSchemaError) as info:
        validate_response(response, plan)
    assert info.value.raw is not None
    assert info.value.failure_code == "schema"
    assert response == before  # validation never repairs or defaults anything


@pytest.mark.parametrize("raw", [None, [], "text", 3, {}])
def test_non_object_or_empty_responses_are_rejected(raw: object) -> None:
    with pytest.raises(DeciderSchemaError):
        validate_response(raw, build_plan("state", config()))


def test_server_rounding_within_tolerance_is_accepted_but_not_beyond() -> None:
    plan = build_plan("state", config())
    ok = recorded_response()
    probs = ok["answers"]["nature_p0"]["probabilities"]
    top = max(probs, key=lambda k: probs[k])
    probs[top] = round(probs[top] + 0.0008, 4)
    validate_response(ok, plan)
    probs[top] = round(probs[top] + 0.01, 4)
    with pytest.raises(DeciderSchemaError, match="sum"):
        validate_response(ok, plan)

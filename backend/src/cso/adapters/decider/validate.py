"""Strict validation of a `/v1/systemone` response. Any deviation raises; nothing is defaulted."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cso.adapters.decider.errors import DeciderSchemaError
from cso.adapters.decider.questions import RequestPlan

SUM_TOLERANCE = 1e-3
_TOP_KEYS = {"model", "answers", "usage", "latency_ms"}  # latency_ms is sent but not in OpenAPI
_CHOICE_KEYS = {"type", "choice", "probabilities", "confidence"}
_NOUL_KEYS = {"type", "noul"}
_TOKEN_KEYS = {"input_tokens", "output_tokens"}


@dataclass(frozen=True)
class ChoiceAnswer:
    """One validated choice answer; probabilities are in the order the option set was asked."""

    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclass(frozen=True)
class ValidatedResponse:
    """A response that passed every check."""

    model: str
    choices: dict[str, ChoiceAnswer]
    nouls: dict[str, float]
    input_tokens: int
    output_tokens: int
    server_latency_ms: float | None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_keys(where: str, got: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
    if missing := required - set(got):
        raise DeciderSchemaError(f"{where}: missing {sorted(missing)}")
    if extra := set(got) - allowed:
        raise DeciderSchemaError(f"{where}: unexpected {sorted(extra)}")


def _validate_choice(name: str, order: tuple[str, ...], answer: object) -> ChoiceAnswer:
    if not isinstance(answer, dict):
        raise DeciderSchemaError(f"{name}: answer is not an object")
    _check_keys(name, answer, _CHOICE_KEYS, _CHOICE_KEYS)
    if answer["type"] != "choice":
        raise DeciderSchemaError(f"{name}: type is {answer['type']!r}, expected 'choice'")
    probs = answer["probabilities"]
    if not isinstance(probs, dict):
        raise DeciderSchemaError(f"{name}: probabilities is not an object")
    if missing := set(order) - set(probs):
        raise DeciderSchemaError(f"{name}: probabilities missing options {sorted(missing)}")
    if extra := set(probs) - set(order):
        raise DeciderSchemaError(f"{name}: probabilities has extra options {sorted(extra)}")
    for option, p in probs.items():
        if not _is_number(p) or not 0.0 <= p <= 1.0:
            raise DeciderSchemaError(f"{name}: probability for {option!r} is not in [0, 1]")
    total = sum(probs.values())
    if abs(total - 1.0) > SUM_TOLERANCE:
        raise DeciderSchemaError(f"{name}: probabilities sum to {total:.6f}, expected 1")
    choice = answer["choice"]
    if not isinstance(choice, str) or choice not in probs:
        raise DeciderSchemaError(f"{name}: choice {choice!r} is not one of the options")
    if probs[choice] < max(probs.values()) - 1e-9:
        raise DeciderSchemaError(f"{name}: choice {choice!r} is not the argmax")
    confidence = answer["confidence"]
    if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
        raise DeciderSchemaError(f"{name}: confidence is not in [0, 1]")
    return ChoiceAnswer(choice, {o: float(probs[o]) for o in order}, float(confidence))


def _validate_noul(name: str, answer: object) -> float:
    if not isinstance(answer, dict):
        raise DeciderSchemaError(f"{name}: answer is not an object")
    _check_keys(name, answer, _NOUL_KEYS, _NOUL_KEYS)
    if answer["type"] != "noul":
        raise DeciderSchemaError(f"{name}: type is {answer['type']!r}, expected 'noul'")
    value = answer["noul"]
    if not _is_number(value) or not 0.0 <= value <= 1.0:
        raise DeciderSchemaError(f"{name}: noul is not in [0, 1]")
    return float(value)


def validate_response(raw: object, plan: RequestPlan) -> ValidatedResponse:
    """Check `raw` against the questions in `plan`; raise DeciderSchemaError on any deviation."""
    try:
        return _validate(raw, plan)
    except DeciderSchemaError as exc:
        if exc.raw is None:
            exc.raw = raw
        raise


def _validate(raw: object, plan: RequestPlan) -> ValidatedResponse:
    if not isinstance(raw, dict):
        raise DeciderSchemaError("response is not an object")
    _check_keys("response", raw, _TOP_KEYS, {"model", "answers", "usage"})
    if not isinstance(raw["model"], str) or not raw["model"]:
        raise DeciderSchemaError("response: model is not a non-empty string")
    usage = raw["usage"]
    if not isinstance(usage, dict):
        raise DeciderSchemaError("usage is not an object")
    _check_keys("usage", usage, _TOKEN_KEYS, _TOKEN_KEYS)
    if not _is_count(usage["input_tokens"]) or not _is_count(usage["output_tokens"]):
        raise DeciderSchemaError("usage: token counts must be non-negative integers")
    latency = raw.get("latency_ms")
    if latency is not None and (not _is_number(latency) or latency < 0):
        raise DeciderSchemaError("response: latency_ms is not a non-negative number")
    answers = raw["answers"]
    if not isinstance(answers, dict):
        raise DeciderSchemaError("answers is not an object")
    expected = set(plan.orders) | set(plan.nouls)
    if set(answers) != expected:
        raise DeciderSchemaError(
            f"answers differ from questions: missing {sorted(expected - set(answers))}, "
            f"unexpected {sorted(set(answers) - expected)}"
        )
    return ValidatedResponse(
        model=raw["model"],
        choices={n: _validate_choice(n, o, answers[n]) for n, o in plan.orders.items()},
        nouls={n: _validate_noul(n, answers[n]) for n in plan.nouls},
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        server_latency_ms=None if latency is None else float(latency),
    )

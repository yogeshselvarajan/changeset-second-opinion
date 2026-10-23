"""Strict validation of a `/v1/systemone` response. Any deviation raises; nothing is defaulted."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .questions import RequestPlan

SUM_TOLERANCE = 1e-3
_TOP_KEYS = {"model", "answers", "usage", "latency_ms"}  # latency_ms is sent but not in OpenAPI
_CHOICE_KEYS = {"type", "choice", "probabilities", "confidence"}
_NOUL_KEYS = {"type", "noul"}


class SchemaError(ValueError):
    """The response deviates from the contract; `raw` keeps it for debugging."""

    def __init__(self, reason: str, raw: object = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw


@dataclass(frozen=True)
class ChoiceAnswer:
    """One validated choice answer."""

    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclass(frozen=True)
class ValidatedResponse:
    """A response that passed every check."""

    model: str
    choices: dict[str, ChoiceAnswer]  # permutation question name -> answer
    nouls: dict[str, float]
    input_tokens: int
    output_tokens: int
    server_latency_ms: float | None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_keys(where: str, got: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
    extra, missing = set(got) - allowed, required - set(got)
    if missing:
        raise SchemaError(f"{where}: missing {sorted(missing)}")
    if extra:
        raise SchemaError(f"{where}: unexpected {sorted(extra)}")


def _validate_choice(name: str, order: tuple[str, ...], answer: object) -> ChoiceAnswer:
    if not isinstance(answer, dict):
        raise SchemaError(f"{name}: answer is not an object")
    _check_keys(name, answer, _CHOICE_KEYS, _CHOICE_KEYS)
    if answer["type"] != "choice":
        raise SchemaError(f"{name}: type is {answer['type']!r}, expected 'choice'")
    probs = answer["probabilities"]
    if not isinstance(probs, dict):
        raise SchemaError(f"{name}: probabilities is not an object")
    missing, extra = set(order) - set(probs), set(probs) - set(order)
    if missing:
        raise SchemaError(f"{name}: probabilities missing options {sorted(missing)}")
    if extra:
        raise SchemaError(f"{name}: probabilities has extra options {sorted(extra)}")
    for option, p in probs.items():
        if not _is_number(p) or not 0.0 <= p <= 1.0:
            raise SchemaError(f"{name}: probability for {option!r} is not a number in [0, 1]")
    total = sum(probs.values())
    if abs(total - 1.0) > SUM_TOLERANCE:
        raise SchemaError(f"{name}: probabilities sum to {total:.6f}, expected 1")
    choice = answer["choice"]
    if not isinstance(choice, str) or choice not in probs:
        raise SchemaError(f"{name}: choice {choice!r} is not one of the options")
    if probs[choice] < max(probs.values()) - 1e-9:
        raise SchemaError(f"{name}: choice {choice!r} is not the argmax of its probabilities")
    confidence = answer["confidence"]
    if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
        raise SchemaError(f"{name}: confidence is not a number in [0, 1]")
    return ChoiceAnswer(choice, {o: float(probs[o]) for o in order}, float(confidence))


def _validate_noul(name: str, answer: object) -> float:
    if not isinstance(answer, dict):
        raise SchemaError(f"{name}: answer is not an object")
    _check_keys(name, answer, _NOUL_KEYS, _NOUL_KEYS)
    if answer["type"] != "noul":
        raise SchemaError(f"{name}: type is {answer['type']!r}, expected 'noul'")
    value = answer["noul"]
    if not _is_number(value) or not 0.0 <= value <= 1.0:
        raise SchemaError(f"{name}: noul is not a number in [0, 1]")
    return float(value)


def validate_response(raw: object, plan: RequestPlan) -> ValidatedResponse:
    """Check `raw` against the questions in `plan`; raise SchemaError on any deviation."""
    try:
        return _validate(raw, plan)
    except SchemaError as exc:
        if exc.raw is None:
            exc.raw = raw
        raise


def _validate(raw: object, plan: RequestPlan) -> ValidatedResponse:
    if not isinstance(raw, dict):
        raise SchemaError("response is not an object")
    _check_keys("response", raw, _TOP_KEYS, {"model", "answers", "usage"})
    if not isinstance(raw["model"], str) or not raw["model"]:
        raise SchemaError("response: model is not a non-empty string")
    usage = raw["usage"]
    if not isinstance(usage, dict):
        raise SchemaError("usage is not an object")
    tokens = {"input_tokens", "output_tokens"}
    _check_keys("usage", usage, tokens, tokens)
    if not _is_count(usage["input_tokens"]) or not _is_count(usage["output_tokens"]):
        raise SchemaError("usage: token counts must be non-negative integers")
    latency = raw.get("latency_ms")
    if latency is not None and (not _is_number(latency) or latency < 0):
        raise SchemaError("response: latency_ms is not a non-negative number")
    answers = raw["answers"]
    if not isinstance(answers, dict):
        raise SchemaError("answers is not an object")
    expected = set(plan.orders) | set(plan.nouls)
    if set(answers) != expected:
        raise SchemaError(
            f"answers differ from questions: missing {sorted(expected - set(answers))}, "
            f"unexpected {sorted(set(answers) - expected)}"
        )
    choices = {n: _validate_choice(n, o, answers[n]) for n, o in plan.orders.items()}
    nouls = {n: _validate_noul(n, answers[n]) for n in plan.nouls}
    return ValidatedResponse(
        model=raw["model"],
        choices=choices,
        nouls=nouls,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        server_latency_ms=None if latency is None else float(latency),
    )

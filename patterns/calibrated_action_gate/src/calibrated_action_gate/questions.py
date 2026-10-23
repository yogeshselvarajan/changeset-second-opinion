"""Build a `/v1/systemone` request: independent choice questions, each asked in K option orders."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChoiceSpec:
    """A choice question: `criteria` maps option code to its description, in base order."""

    name: str
    instructions: str
    criteria: Mapping[str, str]


@dataclass(frozen=True)
class NoulSpec:
    """A yes/no probe; the server returns the probability that the statement is true."""

    name: str
    instructions: str


@dataclass(frozen=True)
class RequestPlan:
    """A request plus what a validator needs to check the response against it."""

    request: dict[str, Any]
    orders: dict[str, tuple[str, ...]]  # permutation question name -> option order asked
    groups: dict[str, tuple[str, ...]]  # spec name -> its permutation question names
    nouls: tuple[str, ...]
    questions_hash: str


def rotations(options: Sequence[str], k: int = 3) -> list[list[str]]:
    """K cyclic rotations with offsets floor(i*n/k): each option takes a different position."""
    n = len(options)
    if n < 2:
        raise ValueError("a choice needs at least two options")
    if not 1 <= k <= n:
        raise ValueError(f"permutations must be between 1 and {n}")
    offsets = [(i * n) // k for i in range(k)]
    return [list(options[o:]) + list(options[:o]) for o in offsets]


def questions_hash(questions: Mapping[str, Any]) -> str:
    """Hash of the constant question block (order preserved, because option order is meaning)."""
    blob = json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_request(
    state: str,
    choices: Sequence[ChoiceSpec],
    nouls: Sequence[NoulSpec] = (),
    *,
    permutations: int = 3,
    model: str | None = None,
) -> RequestPlan:
    """Build the request. Question text and criteria come only from the specs, never the state."""
    questions: dict[str, Any] = {}
    orders: dict[str, tuple[str, ...]] = {}
    groups: dict[str, tuple[str, ...]] = {}
    for spec in choices:
        names = []
        for i, order in enumerate(rotations(list(spec.criteria), permutations)):
            name = f"{spec.name}_p{i}"
            questions[name] = {
                "type": "choice",
                "instructions": spec.instructions,
                "criteria": {code: spec.criteria[code] for code in order},
            }
            orders[name] = tuple(order)
            names.append(name)
        groups[spec.name] = tuple(names)
    for noul in nouls:
        questions[noul.name] = {"type": "noul", "instructions": noul.instructions}
    if len(questions) != len(orders) + len(nouls):
        raise ValueError("question names must be unique")
    request: dict[str, Any] = {"state": state, "questions": questions}
    if model is not None:
        request["model"] = model
    return RequestPlan(
        request=request,
        orders=orders,
        groups=groups,
        nouls=tuple(n.name for n in nouls),
        questions_hash=questions_hash(questions),
    )

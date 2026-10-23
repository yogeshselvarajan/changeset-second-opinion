"""Build the single `/v1/systemone` request: Q1 and Q2 in three option orders, plus two noul probes.

Question text and criteria are constants (instructions below, criteria from the versioned community
config); evidence only ever goes into `state`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cso.domain.config import CommunityConfig

NATURE_INSTRUCTIONS = (
    "Using only the evidence block, pick the description that best matches this changeset."
)
RESPONSE_INSTRUCTIONS = (
    "Pick the single best next step for a volunteer validator who cannot visit the place."
)
NOUL_INSTRUCTIONS: dict[str, str] = {
    "comment_matches_changes": (
        "True if the changeset comment accurately describes the kinds of edits listed in the "
        "evidence."
    ),
    "mature_feature_deleted_probe": (
        "True if any deleted element in the evidence was created more than 365 days before the "
        "changeset or had more than 5 prior versions."
    ),
}
PERMUTATIONS = 3


@dataclass(frozen=True)
class RequestPlan:
    """The request plus what validation needs: the option order asked in each permutation."""

    request: dict[str, Any]
    orders: dict[str, tuple[str, ...]]
    groups: dict[str, tuple[str, ...]]
    nouls: tuple[str, ...]
    questions_hash: str


def rotations(options: list[str], k: int = PERMUTATIONS) -> list[list[str]]:
    """K cyclic rotations with offsets floor(i*n/k), so each option takes a different position."""
    n = len(options)
    if n < 2:
        raise ValueError("a choice needs at least two options")
    if not 1 <= k <= n:
        raise ValueError(f"permutations must be between 1 and {n}")
    return [options[(i * n) // k :] + options[: (i * n) // k] for i in range(k)]


def _hash(questions: dict[str, Any]) -> str:
    blob = json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_plan(
    state: str, config: CommunityConfig, permutations: int = PERMUTATIONS
) -> RequestPlan:
    """Build the request for one rendered state under one community config."""
    specs = {
        "nature": (NATURE_INSTRUCTIONS, config.option_sets.nature),
        "response": (RESPONSE_INSTRUCTIONS, config.option_sets.response),
    }
    questions: dict[str, Any] = {}
    orders: dict[str, tuple[str, ...]] = {}
    groups: dict[str, tuple[str, ...]] = {}
    for key, (instructions, options) in specs.items():
        criteria = {o.code: o.description for o in options}
        names: list[str] = []
        for i, order in enumerate(rotations(list(criteria), permutations)):
            name = f"{key}_p{i}"
            questions[name] = {
                "type": "choice",
                "instructions": instructions,
                "criteria": {code: criteria[code] for code in order},
            }
            orders[name] = tuple(order)
            names.append(name)
        groups[key] = tuple(names)
    for name, instructions in NOUL_INSTRUCTIONS.items():
        questions[name] = {"type": "noul", "instructions": instructions}
    return RequestPlan(
        request={"state": state, "questions": questions},
        orders=orders,
        groups=groups,
        nouls=tuple(NOUL_INSTRUCTIONS),
        questions_hash=_hash(questions),
    )

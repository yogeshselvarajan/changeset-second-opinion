"""Consistency table: which responses are allowed for each nature, and deterministic reconciliation.

Two independent questions can disagree. The gate, not the model, enforces consistency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

ALLOWED_RESPONSES: dict[str, tuple[str, ...]] = {
    "consistent_edit": ("no_action_suggested", "welcome_and_tips"),
    "likely_good_faith_mistake": ("welcome_and_tips", "ask_source_question", "request_local_check"),
    "possible_deliberate_damage": ("escalate_to_experienced_reviewer", "request_local_check"),
    "needs_local_knowledge": ("request_local_check", "ask_source_question"),
}


@dataclass(frozen=True)
class Reconciliation:
    """The response after reconciliation; `reconciled` is true if the model's pick was replaced."""

    response: str
    reconciled: bool
    original: str


def reconcile(
    nature: str,
    response_probabilities: Mapping[str, float],
    allowed: Mapping[str, tuple[str, ...]] = ALLOWED_RESPONSES,
) -> Reconciliation:
    """Keep the model's response if allowed for `nature`; else take the best allowed option."""
    original = max(response_probabilities, key=lambda o: response_probabilities[o])
    permitted = allowed[nature]
    if original in permitted:
        return Reconciliation(original, False, original)
    best = max(permitted, key=lambda o: response_probabilities.get(o, 0.0))
    return Reconciliation(best, True, original)

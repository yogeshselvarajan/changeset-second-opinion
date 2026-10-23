"""Rule baseline v1: the product policy gate's rules R1-R4 mapped to a fixed answer.

This is the *evaluation* baseline of the comparison report. It reads parsed
evidence only, through `cso.domain.policy.evaluate_rules` (the same rules the product gate uses),
never a model answer. v0 used its own copy of the thresholds plus the `new mapper` flag; v1 is
re-pointed at the real gate (ADR-009), so the baseline and the product cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from cso.domain.config import CommunityConfig
from cso.domain.enums import Nature, Response
from cso.domain.models import EvidenceSnapshot
from cso.domain.policy import R1, R2, R3, R4, evaluate_rules, rule_codes

BASELINE_NAME = "rule_baseline_v1"

# Rules that mean "look closely at this deletion or bulk change".
_DAMAGE_RULES = frozenset({R1, R2, R4})


@dataclass(frozen=True)
class RulePrediction:
    """The baseline's fixed answer and the rules that drove it."""

    nature: Nature
    response: Response
    fired: tuple[str, ...]


def rule_baseline(snapshot: EvidenceSnapshot, config: CommunityConfig) -> RulePrediction:
    """Damage/escalate on R1, R2 or R4; needs-local-knowledge on R3 alone; else consistent."""
    fired = rule_codes(evaluate_rules(snapshot, config))
    if _DAMAGE_RULES & set(fired):
        return RulePrediction(
            Nature.POSSIBLE_DELIBERATE_DAMAGE,
            Response.ESCALATE_TO_EXPERIENCED_REVIEWER,
            tuple(fired),
        )
    if R3 in fired:
        return RulePrediction(
            Nature.NEEDS_LOCAL_KNOWLEDGE, Response.REQUEST_LOCAL_CHECK, tuple(fired)
        )
    return RulePrediction(Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED, ())

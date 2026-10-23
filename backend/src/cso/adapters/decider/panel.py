"""Fact panel request: ten yes/no probes plus the nature choice asked once (advisory).

Question text and instructions are constants. The probes are nouls, so no option order is involved;
the nature choice is asked in the single base order of the community config. Evidence goes only into
`state`. The response is checked by the same strict validator as the permutation request.
"""

from __future__ import annotations

from typing import Any

from cso.adapters.decider.questions import NATURE_INSTRUCTIONS, RequestPlan, _hash
from cso.adapters.decider.validate import ValidatedResponse
from cso.domain.config import CommunityConfig
from cso.domain.panel import (
    PANEL_INSTRUCTIONS,
    PANEL_NOUL_IDS,
    AdvisoryNature,
    FactPanel,
    NoulReading,
    classify,
)

PANEL_NATURE_QUESTION = "nature"
if tuple(PANEL_INSTRUCTIONS) != PANEL_NOUL_IDS:  # keep the two constant tables in lockstep
    raise RuntimeError("PANEL_INSTRUCTIONS must list exactly PANEL_NOUL_IDS, in order")


def build_fact_panel_plan(state: str, config: CommunityConfig) -> RequestPlan:
    """Build the panel request for one rendered state under one community config.

    Probe order follows `config.panel.noul_ids`; the config loader already guarantees those ids are
    exactly the known ones, and this re-checks so a hand-built config cannot ask a different panel.
    """
    ids = tuple(config.panel.noul_ids)
    if set(ids) != set(PANEL_INSTRUCTIONS) or len(ids) != len(PANEL_INSTRUCTIONS):
        raise ValueError(f"panel.noul_ids {sorted(ids)} differ from the known panel")
    base_order = [o.code for o in config.option_sets.nature]
    criteria = {o.code: o.description for o in config.option_sets.nature}
    questions: dict[str, Any] = {
        PANEL_NATURE_QUESTION: {
            "type": "choice",
            "instructions": NATURE_INSTRUCTIONS,
            "criteria": {code: criteria[code] for code in base_order},
        }
    }
    for noul_id in ids:
        questions[noul_id] = {"type": "noul", "instructions": PANEL_INSTRUCTIONS[noul_id]}
    return RequestPlan(
        request={"state": state, "questions": questions},
        orders={PANEL_NATURE_QUESTION: tuple(base_order)},
        groups={PANEL_NATURE_QUESTION: (PANEL_NATURE_QUESTION,)},
        nouls=ids,
        questions_hash=_hash(questions),
    )


def build_fact_panel_request(state: str, config: CommunityConfig) -> dict[str, Any]:
    """The `/v1/systemone` request body for the fact panel (see `build_fact_panel_plan`)."""
    return build_fact_panel_plan(state, config).request


def assemble_panel(
    plan: RequestPlan, validated: ValidatedResponse, config: CommunityConfig
) -> FactPanel:
    """Turn a validated panel response into tri-state readings plus the advisory nature."""
    low = config.panel.thresholds.low
    high = config.panel.thresholds.high
    # A calibrated probe uses its own cut points; `low` and `high` above stay the pack default.
    readings = {
        noul_id: NoulReading(
            id=noul_id,
            probability=validated.nouls[noul_id],
            state=classify(
                validated.nouls[noul_id],
                low=config.panel.thresholds_for(noul_id).low,
                high=config.panel.thresholds_for(noul_id).high,
            ),
        )
        for noul_id in plan.nouls
    }
    nature = validated.choices[PANEL_NATURE_QUESTION]
    return FactPanel(
        low=low,
        high=high,
        readings=readings,
        advisory_nature=AdvisoryNature(
            order=list(plan.orders[PANEL_NATURE_QUESTION]),
            probabilities=dict(nature.probabilities),
            choice=nature.choice,
            confidence=nature.confidence,
        ),
        ids=list(plan.nouls),
    )

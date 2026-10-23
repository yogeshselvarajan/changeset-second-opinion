"""Fact panel: yes/no probes over rendered evidence, read as tri-state facts.

The Decider answers extraction-style yes/no questions far more sharply than multi-way judgement,
so the panel is the decision input and the 4-way nature choice is stored as advisory only. A
probability becomes a tri-state fact with two thresholds from the community config
(`panel.thresholds`); the middle band is `unknown`, and `unknown` is always read in the cautious
direction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from cso.domain.models import FrozenModel, Probability

# Version of the composition code (the P1-P6 and N1-N5 tables in `lanes.py`). It is part of every
# configuration's content hash, so a change to the tables makes a new configuration version even
# when no YAML changed. Raise it with any change to how readings turn into a response or nature.
COMPOSITION_VERSION = "1"

# Question ids, in request order. The instruction text for each lives in the Decider adapter
# (`cso.adapters.decider.panel`); the community config lists the ids it expects.
PANEL_NOUL_IDS: tuple[str, ...] = (
    "mature_feature_deleted",
    "nonsense_or_offensive_values",
    "comment_matches_changes",
    "conventions_followed",
    "new_account_first_edits",
    "deleted_own_recent_additions",
    "real_world_change_claimed",
    "discussion_cites_source",
    "mass_retag_single_key",
    "evidence_sufficient",
)

# Question text of each probe: constants, shown to the Decider verbatim and to human labellers
# (so a label answers the same question the model was asked). The Decider adapter imports this.
PANEL_INSTRUCTIONS: dict[str, str] = {
    "mature_feature_deleted": (
        "True if any deleted element in the evidence has age over 365 days or more than 5 prior "
        "versions."
    ),
    "nonsense_or_offensive_values": (
        "True if any new tag value in the evidence is nonsense, a test string, a personal name on "
        "a public feature, or offensive."
    ),
    "comment_matches_changes": (
        "True if the changeset comment describes the kinds of edits listed."
    ),
    "conventions_followed": (
        "True if new or changed tags use ordinary OSM keys and values for that feature type."
    ),
    "new_account_first_edits": (
        "True if the account is less than 7 days old or has fewer than 10 changesets."
    ),
    "deleted_own_recent_additions": (
        "True if deleted elements were created by the same account within the last 30 days."
    ),
    "real_world_change_claimed": (
        "True if the edits assert a real-world change (new shop, closed road, renamed place) that "
        "cannot be verified from tags and history."
    ),
    "discussion_cites_source": (
        "True if the discussion contains the mapper naming a survey, imagery, or other source."
    ),
    "mass_retag_single_key": ("True if more than 20 elements had the same tag key changed."),
    "evidence_sufficient": (
        "True if the coverage block shows all deletions and most modified elements were detailed."
    ),
}

# Plain-language label of each probe for reviewers (API and UI). No judgement words: each names the
# fact asked, not a conclusion about the mapper.
PANEL_LABELS: dict[str, str] = {
    "mature_feature_deleted": "An old or heavily edited feature was deleted",
    "nonsense_or_offensive_values": "New tag values look like nonsense, a test string or a name",
    "comment_matches_changes": "The changeset comment matches the edits",
    "conventions_followed": "New or changed tags follow ordinary OSM conventions",
    "new_account_first_edits": "The account is new or has very few changesets",
    "deleted_own_recent_additions": "Deleted elements were added by the same account recently",
    "real_world_change_claimed": "The edits claim a real-world change that tags cannot confirm",
    "discussion_cites_source": "The discussion names a survey, imagery or other source",
    "mass_retag_single_key": "One tag key was changed on more than 20 elements",
    "evidence_sufficient": "The evidence covers all deletions and most modified elements",
}

DEFAULT_LOW = 0.35
DEFAULT_HIGH = 0.65


class Tri(StrEnum):
    """A noul probability read against the panel thresholds."""

    NO = "no"
    UNKNOWN = "unknown"
    YES = "yes"


# What a `yes` means for review: `concern` raises it, `reassurance` lowers it. Final polarity per
# ADR-009 (the fact panel).
YES_MEANS: dict[str, Literal["concern", "reassurance"]] = {
    "mature_feature_deleted": "concern",
    "nonsense_or_offensive_values": "concern",
    "comment_matches_changes": "reassurance",
    "conventions_followed": "reassurance",
    "new_account_first_edits": "concern",
    "deleted_own_recent_additions": "concern",
    "real_world_change_claimed": "concern",
    "discussion_cites_source": "reassurance",
    "mass_retag_single_key": "concern",
    "evidence_sufficient": "reassurance",
}


# Probes asked and stored but not used by the composition table: none at present.
# `deleted_own_recent_additions` used to be listed here because the parsed evidence carried no
# creator of each deleted element; `ChangedObject.created_by_uid` now supplies it, the compact
# summary reports the count, and the probe is composed as a concern (ADR-009, Amendment 1).
ADVISORY_PROBES: frozenset[str] = frozenset()

# Probes the composition table does not read because a policy rule already decides the same
# question from parsed evidence: `evidence_sufficient` is rule R3 (coverage). They are still asked,
# stored and cross-checked against the parsed facts (ADR-009).
CROSS_CHECK_ONLY_PROBES: frozenset[str] = frozenset({"evidence_sufficient"})


def classify(probability: float, *, low: float = DEFAULT_LOW, high: float = DEFAULT_HIGH) -> Tri:
    """`no` below `low`, `yes` above `high`, `unknown` from `low` to `high` inclusive."""
    if not 0.0 <= low < high <= 1.0:
        raise ValueError("thresholds must satisfy 0 <= low < high <= 1")
    if probability < low:
        return Tri.NO
    if probability > high:
        return Tri.YES
    return Tri.UNKNOWN


def raises_concern(state: Tri, *, yes_means: Literal["concern", "reassurance"]) -> bool:
    """Cautious reading of one fact: is concern raised? `unknown` always counts as raised.

    For a probe where `yes` is a concern, `yes` and `unknown` raise it; for a probe where `yes` is
    reassuring, `no` and `unknown` raise it (silence does not reassure).
    """
    if state is Tri.UNKNOWN:
        return True
    return state is Tri.YES if yes_means == "concern" else state is Tri.NO


class NoulReading(FrozenModel):
    """One panel probe: the model probability and its tri-state reading."""

    id: str
    probability: Probability
    state: Tri

    @property
    def concern(self) -> bool:
        """Cautious reading using the provisional polarity in `YES_MEANS`."""
        return raises_concern(self.state, yes_means=YES_MEANS[self.id])


class AdvisoryNature(FrozenModel):
    """The single-order nature choice; stored for audit and evaluation, never used for lanes."""

    advisory: Literal[True] = True
    order: list[str]
    probabilities: dict[str, Probability]
    choice: str
    confidence: Probability


class FactPanel(FrozenModel):
    """Validated panel answers: readings for every probe plus the advisory nature distribution."""

    low: Probability
    high: Probability
    readings: dict[str, NoulReading]
    advisory_nature: AdvisoryNature
    ids: list[str] = Field(default_factory=list)  # request order

    def state(self, noul_id: str) -> Tri:
        """Tri-state of one probe; KeyError when the id is not in the panel."""
        return self.readings[noul_id].state

    def concerns(self) -> dict[str, bool]:
        """Cautious reading of every probe (`unknown` raises concern)."""
        return {i: self.readings[i].concern for i in self.ids}


__all__ = [
    "ADVISORY_PROBES",
    "CROSS_CHECK_ONLY_PROBES",
    "DEFAULT_HIGH",
    "PANEL_INSTRUCTIONS",
    "DEFAULT_LOW",
    "PANEL_LABELS",
    "PANEL_NOUL_IDS",
    "YES_MEANS",
    "AdvisoryNature",
    "FactPanel",
    "NoulReading",
    "Tri",
    "classify",
    "raises_concern",
]

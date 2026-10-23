"""Instruction wording for the held-out ablations (constants; ADR-009 panel probes).

Every variant covers exactly the ten probe ids in `PANEL_INSTRUCTIONS`. They change only the
wording shown to the Decider; the question each one asks is unchanged.

* `without_cues` drops the concrete cues of the product wording (day and count thresholds and the
  worked examples), keeping the topic. It shows how much the model leans on those cues.
* `paraphrase_1` to `paraphrase_3` reword each question and keep every threshold and example, so
  agreement between them measures sensitivity to wording alone (Cohen's kappa in the report).

These strings are model-facing only. They are not shown to people and are never tuned on held-out
data: they were written before any held-out run.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from cso.domain.panel import PANEL_INSTRUCTIONS

PRODUCT = "product"
WITHOUT_CUES = "without_cues"
PARAPHRASE_NAMES: Final[tuple[str, ...]] = ("paraphrase_1", "paraphrase_2", "paraphrase_3")

_WITHOUT_CUES: dict[str, str] = {
    "mature_feature_deleted": "True if a deleted element in the evidence is old or has been "
    "edited many times.",
    "nonsense_or_offensive_values": "True if a new tag value in the evidence is not a sensible "
    "value.",
    "comment_matches_changes": "True if the changeset comment fits the edits.",
    "conventions_followed": "True if the tags follow normal OSM practice.",
    "new_account_first_edits": "True if the account is new.",
    "deleted_own_recent_additions": "True if deleted elements were added by the same account "
    "recently.",
    "real_world_change_claimed": "True if the edits claim a real-world change that cannot be "
    "checked from the evidence.",
    "discussion_cites_source": "True if the discussion names a source.",
    "mass_retag_single_key": "True if many elements had the same tag key changed.",
    "evidence_sufficient": "True if the evidence covers the deletions and most modified elements.",
}

_PARAPHRASE_1: dict[str, str] = {
    "mature_feature_deleted": "True if at least one deleted element shown is older than 365 "
    "days or has more than 5 earlier versions.",
    "nonsense_or_offensive_values": "True if any newly set tag value looks like nonsense, a test "
    "string, an individual's name on a public feature, or offensive wording.",
    "comment_matches_changes": "True if the changeset comment accurately names the kinds of "
    "edits that were made.",
    "conventions_followed": "True if the new or changed tags are ordinary OSM keys and values "
    "for that kind of feature.",
    "new_account_first_edits": "True if the mapper's account is under 7 days old or has made "
    "fewer than 10 changesets.",
    "deleted_own_recent_additions": "True if the deleted elements were created by this same "
    "account in the past 30 days.",
    "real_world_change_claimed": "True if the edits assert a change in the real world (such as "
    "a new shop, a closed road or a renamed place) that tags and history cannot confirm.",
    "discussion_cites_source": "True if, in the discussion, the mapper names a survey, imagery "
    "or another source.",
    "mass_retag_single_key": "True if the same tag key was changed on more than 20 elements.",
    "evidence_sufficient": "True if the coverage block shows that every deletion and most "
    "modified elements have details.",
}

_PARAPHRASE_2: dict[str, str] = {
    "mature_feature_deleted": "True when a removed element in the evidence has an age above 365 "
    "days, or had over 5 prior versions.",
    "nonsense_or_offensive_values": "True when a new tag value is meaningless, a test entry, a "
    "personal name placed on a public feature, or offensive.",
    "comment_matches_changes": "True when the comment on the changeset matches the types of "
    "edits shown.",
    "conventions_followed": "True when new or modified tags use the usual OSM keys and values "
    "for that type of feature.",
    "new_account_first_edits": "True when the account was created less than 7 days ago or has "
    "under 10 changesets.",
    "deleted_own_recent_additions": "True when removed elements were added by the same account "
    "within the previous 30 days.",
    "real_world_change_claimed": "True when the edits state a real-world change (a new shop, a "
    "closed road, a renamed place) that cannot be checked using tags and history.",
    "discussion_cites_source": "True when the mapper, in the discussion, mentions a survey, "
    "imagery or some other source.",
    "mass_retag_single_key": "True when more than 20 elements have the same tag key changed.",
    "evidence_sufficient": "True when the coverage block shows all deletions, and most modified "
    "elements, were fetched in detail.",
}

_PARAPHRASE_3: dict[str, str] = {
    "mature_feature_deleted": "Answer true if some deleted element listed is more than 365 days "
    "old or has more than 5 earlier versions.",
    "nonsense_or_offensive_values": "Answer true if a new tag value is gibberish, a test string, "
    "a personal name on a public feature, or offensive.",
    "comment_matches_changes": "Answer true if the changeset comment describes the kinds of "
    "edits that are listed.",
    "conventions_followed": "Answer true if the new or changed tags use the ordinary OSM keys "
    "and values for that feature type.",
    "new_account_first_edits": "Answer true if the account is younger than 7 days or has made "
    "fewer than 10 changesets.",
    "deleted_own_recent_additions": "Answer true if the deleted elements were created by the "
    "same account in the last 30 days.",
    "real_world_change_claimed": "Answer true if the edits claim a real-world change (new shop, "
    "closed road, renamed place) that tags and history cannot verify.",
    "discussion_cites_source": "Answer true if the discussion has the mapper naming a survey, "
    "imagery or another source.",
    "mass_retag_single_key": "Answer true if more than 20 elements had one and the same tag key "
    "changed.",
    "evidence_sufficient": "Answer true if the coverage block shows that all deletions and most "
    "modified elements were detailed.",
}

INSTRUCTION_VARIANTS = MappingProxyType(
    {
        WITHOUT_CUES: MappingProxyType(_WITHOUT_CUES),
        "paraphrase_1": MappingProxyType(_PARAPHRASE_1),
        "paraphrase_2": MappingProxyType(_PARAPHRASE_2),
        "paraphrase_3": MappingProxyType(_PARAPHRASE_3),
    }
)

for _name, _texts in INSTRUCTION_VARIANTS.items():  # fail at import if a variant drifts
    if tuple(_texts) != tuple(PANEL_INSTRUCTIONS):
        raise RuntimeError(f"variant {_name!r} must cover exactly the panel probes, in order")

# Evidence cues that the product wording carries and `without_cues` must not: a test asserts it.
CUE_FRAGMENTS: Final[tuple[str, ...]] = ("365", "30 days", "7 days", "10 changesets", "20 elements")


def instructions_for(name: str) -> dict[str, str]:
    """The probe instructions of a named variant ('product' is the shipped wording)."""
    if name == PRODUCT:
        return dict(PANEL_INSTRUCTIONS)
    try:
        return dict(INSTRUCTION_VARIANTS[name])
    except KeyError:
        raise ValueError(f"unknown instruction variant {name!r}") from None

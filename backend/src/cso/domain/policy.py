"""Deterministic policy gate: rules R1-R4 from parsed evidence, R5 and R6 constructors.

Inputs are the parsed `EvidenceSnapshot` (ages, counts, coverage, stage-1 flags) and the run status,
never model answers. A rule missing from the community config still applies with the documented
defaults, so a config edit cannot disable a safety rule by omission.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cso.domain.config import CommunityConfig, ConfigError
from cso.domain.enums import ChangeAction, OsmType, Response, Severity
from cso.domain.fixtures import plausible_edit_time_count
from cso.domain.models import ChangedObject, Coverage, EvidenceSnapshot, RuleHit

R1 = "R1"
R2 = "R2"
R3 = "R3"
R4 = "R4"
R5 = "R5"
R6 = "R6"
EVIDENCE_RULES = (R1, R2, R3, R4)

_MAX_LISTED_ELEMENTS = 10

_DEFAULTS: dict[str, tuple[str, dict[str, Any]]] = {
    R1: ("Mature deletion", {"min_age_days": 365, "min_prior_versions": 5}),
    R2: (
        "Mass change",
        {"osmcha_reasons": ["mass deletion", "mass modification", "possible import"]},
    ),
    R3: (
        "Coverage",
        {"min_score": 0.5, "max_gap_ratio": 0.2, "drafting_limited_to": "ask_source_question"},
    ),
    R4: ("New account with deletions", {"account_age_days_lt": 7}),
    R5: (
        "Escalation requires signal",
        {"min_damage_probability": 0.5, "downgrade_to": "ask_source_question"},
    ),
    R6: ("No model output", {}),
}


def rule_label(config: CommunityConfig, code: str) -> str:
    """Label of a rule from the config, else the documented default."""
    try:
        return config.rule(code).label
    except KeyError:
        return _DEFAULTS[code][0]


def rule_params(config: CommunityConfig, code: str) -> dict[str, Any]:
    """Parameters of a rule: documented defaults overlaid with the community config."""
    params = dict(_DEFAULTS[code][1])
    try:
        params.update(config.rule(code).params)
    except KeyError:
        pass
    return params


def _number(params: Mapping[str, Any], code: str, key: str) -> float:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"rule {code}: param '{key}' must be a number, got {value!r}")
    return float(value)


def _strings(params: Mapping[str, Any], code: str, key: str) -> list[str]:
    value = params[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"rule {code}: param '{key}' must be a list of strings, got {value!r}")
    return list(value)


def _response(params: Mapping[str, Any], code: str, key: str) -> Response:
    value = params[key]
    try:
        return Response(value)
    except ValueError:
        raise ConfigError(
            f"rule {code}: param '{key}' is not a response option: {value!r}"
        ) from None


def _hit(config: CommunityConfig, code: str, severity: Severity, why: dict[str, object]) -> RuleHit:
    return RuleHit(code=code, label=rule_label(config, code), severity=severity, triggered_by=why)


# ------------------------------------------------------------------------------------- R1


def mature_deletions(snapshot: EvidenceSnapshot, config: CommunityConfig) -> list[ChangedObject]:
    """Deleted elements older than `min_age_days` or with at least `min_prior_versions` versions."""
    params = rule_params(config, R1)
    min_age = _number(params, R1, "min_age_days")
    min_versions = _number(params, R1, "min_prior_versions")
    return [
        element
        for element in snapshot.elements
        if element.action is ChangeAction.DELETE
        and (
            (element.age_days is not None and element.age_days > min_age)
            or (element.version_before is not None and element.version_before >= min_versions)
        )
    ]


def _r1(snapshot: EvidenceSnapshot, config: CommunityConfig) -> RuleHit | None:
    elements = mature_deletions(snapshot, config)
    if not elements:
        return None
    params = rule_params(config, R1)
    return _hit(
        config,
        R1,
        Severity.BLOCK,
        {
            "count": len(elements),
            "elements": [
                {
                    "type": e.osm_type.value,
                    "id": e.osm_id,
                    "age_days": e.age_days,
                    "version_before": e.version_before,
                }
                for e in elements[:_MAX_LISTED_ELEMENTS]
            ],
            "min_age_days": params["min_age_days"],
            "min_prior_versions": params["min_prior_versions"],
        },
    )


# ------------------------------------------------------------------------------------- R2


def _r2(snapshot: EvidenceSnapshot, config: CommunityConfig) -> RuleHit | None:
    wanted = {r.casefold() for r in _strings(rule_params(config, R2), R2, "osmcha_reasons")}
    matched = sorted({f for f in snapshot.flags if f.casefold() in wanted})
    if not matched:
        return None
    return _hit(config, R2, Severity.WARN, {"osmcha_reasons": matched})


# ------------------------------------------------------------------------------------- R3


def gap_ratio(coverage: Coverage) -> float:
    """History gaps as a share of the elements detailed (1.0 when gaps exist but none detailed)."""
    gaps = len(coverage.history_gaps)
    if coverage.elements_detailed > 0:
        return gaps / coverage.elements_detailed
    return 1.0 if gaps else 0.0


def coverage_insufficient(coverage: Coverage, config: CommunityConfig) -> bool:
    """True when R3 fires: low coverage score or too many history gaps."""
    params = rule_params(config, R3)
    return coverage.score < _number(params, R3, "min_score") or gap_ratio(coverage) > _number(
        params, R3, "max_gap_ratio"
    )


def _r3(snapshot: EvidenceSnapshot, config: CommunityConfig) -> RuleHit | None:
    if not coverage_insufficient(snapshot.coverage, config):
        return None
    params = rule_params(config, R3)
    coverage = snapshot.coverage
    limit = _response(params, R3, "drafting_limited_to")
    return _hit(
        config,
        R3,
        Severity.WARN,
        {
            "score": coverage.score,
            "min_score": params["min_score"],
            "gap_ratio": gap_ratio(coverage),
            "max_gap_ratio": params["max_gap_ratio"],
            "elements_in_changeset": coverage.elements_in_changeset,
            "elements_detailed": coverage.elements_detailed,
            "history_gaps": len(coverage.history_gaps),
            "elements_skipped_budget": coverage.elements_skipped_budget,
            "drafting_limited_to": limit.value,
        },
    )


# ------------------------------------------------------------------------------------- R4


def delete_count(snapshot: EvidenceSnapshot) -> int:
    """Deleted elements in the changeset: the parsed osmChange count, else the detailed elements."""
    counted = snapshot.element_counts.get(ChangeAction.DELETE)
    if counted is not None:
        return counted
    return sum(1 for e in snapshot.elements if e.action is ChangeAction.DELETE)


def _r4(snapshot: EvidenceSnapshot, config: CommunityConfig) -> RuleHit | None:
    age = None if snapshot.user is None else snapshot.user.account_age_days
    if age is None:
        return None  # unknown age cannot trigger; the coverage record shows the failed profile
    limit = _number(rule_params(config, R4), R4, "account_age_days_lt")
    deletes = delete_count(snapshot)
    if age >= limit or deletes <= 0:
        return None
    return _hit(
        config,
        R4,
        Severity.WARN,
        {"account_age_days": age, "account_age_days_lt": limit, "deletions": deletes},
    )


# ------------------------------------------------------------------------- public entry points


def evaluate_rules(snapshot: EvidenceSnapshot, config: CommunityConfig) -> list[RuleHit]:
    """Rules R1-R4 over parsed evidence, in code order. No model output is consulted."""
    hits = (
        _r1(snapshot, config),
        _r2(snapshot, config),
        _r3(snapshot, config),
        _r4(snapshot, config),
    )
    return [h for h in hits if h is not None]


def no_model_hit(config: CommunityConfig, failure_code: str | None = None) -> RuleHit:
    """R6: the run produced no model output, so the lane is `rules_only`."""
    return _hit(config, R6, Severity.INFO, {"failure_code": failure_code})


def escalation_downgrade_hit(
    config: CommunityConfig,
    *,
    damage_probability: float,
    original: Response,
    downgraded_to: Response,
) -> RuleHit:
    """R5: an escalation without signal was downgraded."""
    params = rule_params(config, R5)
    return _hit(
        config,
        R5,
        Severity.INFO,
        {
            "p_possible_deliberate_damage": damage_probability,
            "min_damage_probability": params["min_damage_probability"],
            "from": original.value,
            "to": downgraded_to.value,
        },
    )


def escalation_threshold(config: CommunityConfig) -> float:
    """R5 `min_damage_probability`."""
    return _number(rule_params(config, R5), R5, "min_damage_probability")


def escalation_downgrade_target(config: CommunityConfig) -> Response:
    """R5 `downgrade_to`."""
    return _response(rule_params(config, R5), R5, "downgrade_to")


def rule_codes(hits: Iterable[RuleHit]) -> list[str]:
    """Sorted codes of the hits."""
    return sorted({h.code for h in hits})


def has_rule(hits: Sequence[RuleHit], code: str) -> bool:
    """Whether a hit with this code is present."""
    return any(h.code == code for h in hits)


# ----------------------------------------------------------------------- parsed panel facts
#
# The fact panel asks the Decider yes/no questions. Five of them can also be computed exactly from
# parsed evidence; these helpers do that. They are cross-checks for the panel and for evaluation,
# never gate inputs from the model (invariant 3), and R1-R4 stay the authority.

MASS_RETAG_MIN_ELEMENTS = 20  # "more than 20 elements had the same tag key changed"
NEW_ACCOUNT_MAX_AGE_DAYS = 7
NEW_ACCOUNT_MIN_CHANGESETS = 10
OWN_RECENT_MAX_AGE_DAYS = 30  # "created by the same account within the last 30 days"


def changed_key_counts(snapshot: EvidenceSnapshot) -> list[tuple[str, int]]:
    """Tag keys changed on modified elements and how many distinct elements changed each.

    Only modifications count: a deletion drops every tag and a creation adds them, and neither is a
    re-tag. Counted over the elements with tag diffs (the detailed ones), most frequent first, ties
    broken by key so the order is deterministic.
    """
    modified = {
        (e.osm_type, e.osm_id) for e in snapshot.elements if e.action is ChangeAction.MODIFY
    }
    per_key: dict[str, set[tuple[OsmType, int]]] = defaultdict(set)
    for diff in snapshot.tag_diffs:
        ref = (diff.osm_type, diff.osm_id)
        if ref in modified:
            per_key[diff.key].add(ref)
    return sorted(
        ((key, len(refs)) for key, refs in per_key.items()), key=lambda kv: (-kv[1], kv[0])
    )


def mass_retag_key(snapshot: EvidenceSnapshot) -> tuple[str, int] | None:
    """The most-changed tag key when more than 20 elements changed it, else None."""
    counts = changed_key_counts(snapshot)
    if counts and counts[0][1] > MASS_RETAG_MIN_ELEMENTS:
        return counts[0]
    return None


def new_account_first_edits(snapshot: EvidenceSnapshot) -> bool | None:
    """Account younger than 7 days or with fewer than 10 changesets when the edit was made.

    True: age under 7 days, or an edit-time count under 10; also True when only the account's
    current total is known and that total is under 10 (counts only grow, so the edit-time count was
    lower still). False: age at least 7 days and an edit-time count of 10 or more. None otherwise:
    a current total of 10 or more does not show the edit-time count was 10 or more, and an unknown
    age with a count of 10 or more cannot rule out a young account. The edit-time count comes from
    the changeset's own `changesets_count` tag, used only when it does not exceed the account's
    current total; an old snapshot without a basis counts as current.
    """
    user = snapshot.user
    age = user.account_age_days if user is not None else None
    edit_time = snapshot.changeset.changesets_count
    current: int | None = None
    if user is not None and user.changesets_count is not None:
        if user.changesets_count_basis == "edit_time":
            edit_time = user.changesets_count if edit_time is None else edit_time
        else:
            current = user.changesets_count
            # the tag is a mapper claim: ignore one that exceeds the account's total (F-M5)
            edit_time = plausible_edit_time_count(edit_time, current)
    if age is None and edit_time is None and current is None:
        return None
    if age is not None and age < NEW_ACCOUNT_MAX_AGE_DAYS:
        return True
    if edit_time is not None and edit_time < NEW_ACCOUNT_MIN_CHANGESETS:
        return True
    if current is not None and current < NEW_ACCOUNT_MIN_CHANGESETS:
        return True
    if age is not None and edit_time is not None:
        return False  # old enough, and 10 or more changesets at the time
    return None


def own_recent_deletions(snapshot: EvidenceSnapshot) -> tuple[int, int]:
    """Deleted elements created by this changeset's account within 30 days; and how many are known.

    Returns `(own_recent, determinable)`: `own_recent` counts detailed deletions whose creator uid
    equals the changeset uid and whose age is at most 30 days; `determinable` counts detailed
    deletions whose creator and age are both known, so the caller can tell "none" from "unknown".
    """
    uid = snapshot.changeset.uid
    own_recent = determinable = 0
    for e in snapshot.elements:
        if e.action is not ChangeAction.DELETE:
            continue
        if uid is None or e.created_by_uid is None or e.age_days is None:
            continue
        determinable += 1
        if e.created_by_uid == uid and e.age_days <= OWN_RECENT_MAX_AGE_DAYS:
            own_recent += 1
    return own_recent, determinable


def deleted_own_recent_additions(snapshot: EvidenceSnapshot) -> bool | None:
    """True when a detailed deletion was created by the same account within 30 days.

    False only when no deletion qualifies and every deletion of the changeset is determinable;
    None (cannot be computed) otherwise, for example when creators were not reconstructed.
    """
    own_recent, determinable = own_recent_deletions(snapshot)
    if own_recent > 0:
        return True
    if determinable >= delete_count(snapshot):
        return False
    return None


def deletions_detailed(snapshot: EvidenceSnapshot) -> bool:
    """Every deleted element of the changeset has details (a prior version was reconstructed)."""
    detailed = sum(1 for e in snapshot.elements if e.action is ChangeAction.DELETE)
    return detailed >= delete_count(snapshot)


@dataclass(frozen=True, slots=True)
class ParsedFacts:
    """Panel questions computed exactly from parsed evidence (`None` = cannot be computed)."""

    mature_feature_deleted: bool
    new_account_first_edits: bool | None
    deleted_own_recent_additions: bool | None
    mass_retag_single_key: bool
    evidence_sufficient: bool

    def as_dict(self) -> dict[str, bool | None]:
        """Keyed by panel probe id."""
        return {
            "mature_feature_deleted": self.mature_feature_deleted,
            "new_account_first_edits": self.new_account_first_edits,
            "deleted_own_recent_additions": self.deleted_own_recent_additions,
            "mass_retag_single_key": self.mass_retag_single_key,
            "evidence_sufficient": self.evidence_sufficient,
        }


def parsed_facts(snapshot: EvidenceSnapshot, config: CommunityConfig) -> ParsedFacts:
    """The five panel facts derivable from parsed evidence."""
    return ParsedFacts(
        mature_feature_deleted=bool(mature_deletions(snapshot, config)),
        new_account_first_edits=new_account_first_edits(snapshot),
        deleted_own_recent_additions=deleted_own_recent_additions(snapshot),
        mass_retag_single_key=mass_retag_key(snapshot) is not None,
        evidence_sufficient=(
            not coverage_insufficient(snapshot.coverage, config) and deletions_detailed(snapshot)
        ),
    )

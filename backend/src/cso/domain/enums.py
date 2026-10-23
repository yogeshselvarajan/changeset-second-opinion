"""Enumerations shared across the application; values are part of the public API contract."""

from enum import StrEnum


class Lane(StrEnum):
    """Suggested-disposition bucket used to order the queue (nothing is hidden)."""

    LOOKS_CONSISTENT = "looks_consistent"
    REVIEW_SUGGESTED = "review_suggested"
    NEEDS_LOCAL_KNOWLEDGE = "needs_local_knowledge"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RULES_ONLY = "rules_only"


class Band(StrEnum):
    """Backend-assigned sharpness band of the model output."""

    CONFIDENT = "confident"
    UNSURE = "unsure"
    CANNOT_TELL = "cannot_tell"


class Nature(StrEnum):
    """Q1 option set: what the changeset looks like."""

    CONSISTENT_EDIT = "consistent_edit"
    LIKELY_GOOD_FAITH_MISTAKE = "likely_good_faith_mistake"
    POSSIBLE_DELIBERATE_DAMAGE = "possible_deliberate_damage"
    NEEDS_LOCAL_KNOWLEDGE = "needs_local_knowledge"


class Response(StrEnum):
    """Q2 option set: suggested next step for the reviewer."""

    NO_ACTION_SUGGESTED = "no_action_suggested"
    WELCOME_AND_TIPS = "welcome_and_tips"
    ASK_SOURCE_QUESTION = "ask_source_question"
    REQUEST_LOCAL_CHECK = "request_local_check"
    ESCALATE_TO_EXPERIENCED_REVIEWER = "escalate_to_experienced_reviewer"


class Disposition(StrEnum):
    """What a human reviewer decided."""

    AGREE = "agree"
    DIFFERENT_RESPONSE = "different_response"
    NEEDS_SURVEY = "needs_survey"
    DISAGREE_WITH_MODEL = "disagree_with_model"
    NO_ACTION = "no_action"


class CaseStatus(StrEnum):
    """Lifecycle state of a review case (staleness is a separate flag)."""

    NEW = "new"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    DECIDED = "decided"


class JobStatus(StrEnum):
    """State machine of a durable background job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    """Kind of background work."""

    ANALYZE = "analyze"
    DRAFT = "draft"


class DraftStatus(StrEnum):
    """Validation outcome of a drafted comment."""

    GENERATED = "generated"
    VALIDATED = "validated"
    REJECTED_BY_VALIDATOR = "rejected_by_validator"
    TEMPLATE_FALLBACK = "template_fallback"


class EvidenceSource(StrEnum):
    """Where a fact came from: live API, replayed fixture, or computed by code."""

    OSM_API = "osm_api"
    REPLAY = "replay"
    DERIVED = "derived"


class CoverageGapReason(StrEnum):
    """Why a prior version could not be reconstructed."""

    REDACTED = "redacted"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    BUDGET = "budget"


class FetchStatus(StrEnum):
    """Outcome of an auxiliary fetch (user profile, discussion)."""

    FETCHED = "fetched"
    FAILED = "failed"
    SKIPPED = "skipped"


class OsmType(StrEnum):
    """OSM element type."""

    NODE = "node"
    WAY = "way"
    RELATION = "relation"


class ChangeAction(StrEnum):
    """Action an element underwent in the changeset."""

    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class TagChange(StrEnum):
    """Kind of tag difference between two versions."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class Severity(StrEnum):
    """Severity of a policy rule hit."""

    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class RunStatus(StrEnum):
    """Outcome of an analysis run."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"

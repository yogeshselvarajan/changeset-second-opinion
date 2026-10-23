"""SQLAlchemy tables for SQLite (default) and Postgres, with the data model of the docs site."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


class UTCDateTime(sa.TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every dialect (SQLite drops the offset, so restore it)."""

    impl = sa.DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: persistence stores timezone-aware values only")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow() -> datetime:
    """Current time, timezone-aware UTC."""
    return datetime.now(UTC)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base; `Base.metadata` is what alembic compares migrations against."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


# Tables whose rows are never updated or deleted by the application: snapshots, runs, drafts,
# outcomes and audit events are immutable, and a correction is a new row.
IMMUTABLE_TABLES = frozenset(
    {"evidence_snapshots", "analysis_runs", "drafts", "human_outcomes", "audit_events"}
)


class CommunityConfigRow(Base):
    """A stored community configuration version; only `is_active` changes after insert."""

    __tablename__ = "community_configs"

    version: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    yaml: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    # The community pack this version came from; NULL for versions stored before packs existed.
    pack_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # The calibration folded into this version's thresholds; NULL when none was applied.
    calibration_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class WorkspaceScoped:
    """Rows that belong to a workspace. NULL means the default workspace: the instance has one
    today, and a plain nullable column is all SQLite can add without rebuilding the table (the
    link to `workspaces.id` is by convention, not a foreign key)."""

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)


class WorkspaceRow(Base):
    """The instance's public face and switches (migration 0007), saved with If-Match."""

    __tablename__ = "workspaces"
    __table_args__ = (sa.Index("ix_workspaces_slug", "slug", unique=True),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(sa.Text)
    name: Mapped[str] = mapped_column(sa.Text)
    tagline: Mapped[str] = mapped_column(sa.Text)
    accent_hex: Mapped[str] = mapped_column(sa.Text)
    logo_svg: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    community_paragraph: Mapped[str] = mapped_column(sa.Text)
    active_pack: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    lane_thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    calibration_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    osm_signin_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=sa.true()
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1")
    # Migration 0009: the identity that claimed the workspace in the web app (NULL until then).
    owner_identity_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)


class InviteCodeRow(Base, WorkspaceScoped):
    """A hashed invite code that grants a role (the auth package owns the behaviour)."""

    __tablename__ = "invite_codes"
    __table_args__ = (sa.Index("ix_invite_codes_code_id", "code_id", unique=True),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    code_hash: Mapped[str] = mapped_column(sa.Text, unique=True)
    role: Mapped[str] = mapped_column(sa.Text)
    label: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    disabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    # Migration 0002. `code_hash` is a salted argon2 hash and cannot be looked up, so the public
    # `code_id` part of the invite code finds the row and argon2 checks the secret part.
    code_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    max_uses: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Migration 0007: when an admin revoked the code, and who made it.
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class IdentityRow(Base):
    """An OpenStreetMap account that signed in (migration 0006). Holds no token, ever."""

    __tablename__ = "identities"
    __table_args__ = (sa.Index("ix_identities_osm_uid", "osm_uid", unique=True),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    osm_uid: Mapped[int] = mapped_column(sa.BigInteger)
    display_name: Mapped[str] = mapped_column(sa.Text)
    account_created: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OAuthStateRow(Base):
    """One pending OpenStreetMap sign-in: the hashed `state` and its PKCE verifier (10 minutes)."""

    __tablename__ = "oauth_states"

    state_hash: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    verifier: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class SessionRow(Base):
    """A reviewer session created from an invite code or an OpenStreetMap sign-in."""

    __tablename__ = "sessions"
    __table_args__ = (sa.Index("ix_sessions_token_hash", "token_hash", unique=True),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    # NULL for a session opened by signing in with OpenStreetMap (migration 0006); `identity_id`
    # is set for those and NULL for invite-code sessions.
    invite_code_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("invite_codes.id"), nullable=True
    )
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("identities.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(sa.Text)
    role: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    # Migration 0002. The cookie carries a random token; only its sha256 is stored, and the CSRF
    # token is bound to the session the same way (double-submit plus session binding).
    token_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    csrf_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ReviewCaseRow(Base, WorkspaceScoped):
    """One flagged changeset. Carries the mutable pointers and queue summary columns."""

    __tablename__ = "review_cases"
    __table_args__ = (
        sa.Index("ix_review_cases_queue", "lane_rank", sa.text("created_at DESC"), "id"),
        sa.Index("ix_review_cases_status", "status", sa.text("created_at DESC")),
        sa.Index("ix_review_cases_updated_at", "updated_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    changeset_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True)
    status: Mapped[str] = mapped_column(sa.Text, default="new", server_default="new")
    lane: Mapped[str] = mapped_column(sa.Text, default="rules_only", server_default="rules_only")
    lane_rank: Mapped[int] = mapped_column(sa.Integer, default=3, server_default="3")
    stale: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    uid: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    user_display: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    editor: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    place_label: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # The mapper's own changeset comment (untrusted text), so a queue row reads as a sentence.
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    element_create: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    element_modify: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    element_delete: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    flags: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    # Summary of the latest run/outcome, denormalised so the queue is one indexed read (A1).
    band: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    nature: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    response: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    latest_outcome: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    coverage_score: Mapped[float] = mapped_column(sa.Float, default=1.0, server_default="1.0")
    # Pointers carry no FK: review_cases <-> snapshots/runs/drafts would be circular.
    latest_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    latest_run_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    latest_draft_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    outcome_version: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class EvidenceSnapshotRow(Base):
    """IMMUTABLE. Everything fetched about a changeset at one time."""

    __tablename__ = "evidence_snapshots"
    __table_args__ = (
        sa.UniqueConstraint("case_id", "evidence_version", name="uq_evidence_snapshots_version"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("review_cases.id"))
    evidence_version: Mapped[str] = mapped_column(sa.Text)
    source: Mapped[str] = mapped_column(sa.Text)
    provisional: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONType)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONType)  # changeset, user, flags, element_counts
    elements: Mapped[list[Any]] = mapped_column(JSONType)
    tag_diffs: Mapped[list[Any]] = mapped_column(JSONType)
    discussion: Mapped[list[Any]] = mapped_column(JSONType)
    rendered_text: Mapped[str] = mapped_column(sa.Text, default="")
    rendered_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class JobRow(Base):
    """A durable background job; walks a state machine, so it is mutable."""

    __tablename__ = "jobs"
    __table_args__ = (
        sa.Index("ix_jobs_claim", "status", "run_after", sa.text("priority DESC"), "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("review_cases.id"))
    kind: Mapped[str] = mapped_column(sa.Text)
    evidence_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    response_type: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)  # draft jobs
    # (case, kind, evidence_version, run_id, response_type) with NULLs normalised to '', because a
    # UNIQUE over nullable columns does not deduplicate on SQLite or Postgres.
    job_key: Mapped[str] = mapped_column(sa.Text, unique=True)
    status: Mapped[str] = mapped_column(sa.Text, default="queued")
    step: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    priority: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(sa.Integer, default=3, server_default="3")
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)  # queuing request
    result_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AnalysisRunRow(Base, WorkspaceScoped):
    """IMMUTABLE. One Decider + policy-gate run on one snapshot."""

    __tablename__ = "analysis_runs"
    __table_args__ = (sa.Index("ix_analysis_runs_case", "case_id", sa.text("created_at DESC")),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("review_cases.id"))
    snapshot_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("evidence_snapshots.id"))
    # SET NULL is a referential action, not an app UPDATE: it lets terminal jobs be purged.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    config_version: Mapped[str] = mapped_column(sa.ForeignKey("community_configs.version"))
    decider_model: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    decider_checkpoint: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.Text)
    failure_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    lane: Mapped[str] = mapped_column(sa.Text)
    band: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    nature: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    response: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    reconciled: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    nature_probabilities: Mapped[dict[str, Any]] = mapped_column(JSONType)
    response_probabilities: Mapped[dict[str, Any]] = mapped_column(JSONType)
    order_sensitivity: Mapped[float] = mapped_column(sa.Float, default=0.0)
    rules_fired: Mapped[list[Any]] = mapped_column(JSONType)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    latency_ms: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class DraftRow(Base, WorkspaceScoped):
    """IMMUTABLE. A comment candidate; a human always edits and posts it."""

    __tablename__ = "drafts"
    __table_args__ = (
        sa.Index("ix_drafts_run", "run_id", "response_type", sa.text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("review_cases.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id"))
    response_type: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    model_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    greeting: Mapped[str] = mapped_column(sa.Text)
    body: Mapped[str] = mapped_column(sa.Text)
    closing: Mapped[str] = mapped_column(sa.Text)
    cited_evidence_ids: Mapped[list[Any]] = mapped_column(JSONType)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONType)
    prompt_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    config_version: Mapped[str] = mapped_column(sa.ForeignKey("community_configs.version"))
    usage: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class HumanOutcomeRow(Base, WorkspaceScoped):
    """APPEND-ONLY. A reviewer decision; a correction is a new row."""

    __tablename__ = "human_outcomes"
    __table_args__ = (
        sa.Index("ix_human_outcomes_case", "case_id", sa.text("created_at DESC")),
        sa.Index("ix_human_outcomes_history", "created_at", "reviewer_display"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("review_cases.id"))
    run_id_seen: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("analysis_runs.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("sessions.id"), nullable=True
    )
    reviewer_display: Mapped[str] = mapped_column(sa.Text)
    disposition: Mapped[str] = mapped_column(sa.Text)
    response_type: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    final_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Facts the reviewer judged wrong on a disagreement: {probe id: "yes" | "no"}; NULL otherwise.
    probe_corrections: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # The OpenStreetMap identity that decided, when the session came from signing in with OSM.
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("identities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class CalibrationRow(Base):
    """IMMUTABLE. One applied calibration: the thresholds fitted from reviewer outcomes."""

    __tablename__ = "calibrations"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    pack_id: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    n_outcomes: Mapped[int] = mapped_column(sa.Integer)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONType)
    band_report: Mapped[list[Any]] = mapped_column(JSONType)
    created_by: Mapped[str] = mapped_column(sa.Text)


class AuditEventRow(Base, WorkspaceScoped):
    """APPEND-ONLY. Who did what, with the request id."""

    __tablename__ = "audit_events"
    __table_args__ = (sa.Index("ix_audit_events_case", "case_id", "id"),)

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("review_cases.id"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("sessions.id"), nullable=True
    )
    actor: Mapped[str] = mapped_column(sa.Text)
    action: Mapped[str] = mapped_column(sa.Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    request_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


IMMUTABLE_MODELS: tuple[type[Base], ...] = (
    EvidenceSnapshotRow,
    AnalysisRunRow,
    DraftRow,
    HumanOutcomeRow,
    AuditEventRow,
)

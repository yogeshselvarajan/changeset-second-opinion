"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-17

Written from autogenerate output and corrected by hand: portable JSON/datetime types, `false()`
boolean defaults (valid on Postgres), and the DESC indexes that SQLite autogenerate cannot see.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "community_configs",
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("yaml", sa.Text(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("version", name=op.f("pk_community_configs")),
    )
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("disabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invite_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_invite_codes_code_hash")),
    )
    op.create_table(
        "review_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("changeset_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default="new", nullable=False),
        sa.Column("lane", sa.Text(), server_default="rules_only", nullable=False),
        sa.Column("lane_rank", sa.Integer(), server_default="3", nullable=False),
        sa.Column("stale", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=True),
        sa.Column("user_display", sa.Text(), nullable=True),
        sa.Column("editor", sa.Text(), nullable=True),
        sa.Column("place_label", sa.Text(), nullable=True),
        sa.Column("element_create", sa.Integer(), server_default="0", nullable=False),
        sa.Column("element_modify", sa.Integer(), server_default="0", nullable=False),
        sa.Column("element_delete", sa.Integer(), server_default="0", nullable=False),
        sa.Column("flags", JSON, nullable=False),
        sa.Column("band", sa.Text(), nullable=True),
        sa.Column("nature", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("latest_outcome", sa.Text(), nullable=True),
        sa.Column("coverage_score", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("latest_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("latest_run_id", sa.Uuid(), nullable=True),
        sa.Column("latest_draft_id", sa.Uuid(), nullable=True),
        sa.Column("outcome_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_cases")),
        sa.UniqueConstraint("changeset_id", name=op.f("uq_review_cases_changeset_id")),
    )
    op.create_index(
        "ix_review_cases_queue",
        "review_cases",
        ["lane_rank", sa.text("created_at DESC"), "id"],
    )
    op.create_index(
        "ix_review_cases_status", "review_cases", ["status", sa.text("created_at DESC")]
    )
    op.create_index("ix_review_cases_updated_at", "review_cases", ["updated_at"])

    op.create_table(
        "evidence_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_version", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", _ts(), nullable=False),
        sa.Column("coverage", JSON, nullable=False),
        sa.Column("raw", JSON, nullable=False),
        sa.Column("elements", JSON, nullable=False),
        sa.Column("tag_diffs", JSON, nullable=False),
        sa.Column("discussion", JSON, nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("rendered_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["review_cases.id"],
            name=op.f("fk_evidence_snapshots_case_id_review_cases"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_snapshots")),
        sa.UniqueConstraint("case_id", "evidence_version", name="uq_evidence_snapshots_version"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("evidence_version", sa.Text(), nullable=True),
        sa.Column("response_type", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("step", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("run_after", _ts(), nullable=False),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", _ts(), nullable=True),
        sa.Column("lease_expires_at", _ts(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result_ref", JSON, nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["review_cases.id"], name=op.f("fk_jobs_case_id_review_cases")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("job_key", name=op.f("uq_jobs_job_key")),
    )
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["status", "run_after", sa.text("priority DESC"), "created_at"],
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invite_code_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("expires_at", _ts(), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invite_code_id"],
            ["invite_codes.id"],
            name=op.f("fk_sessions_invite_code_id_invite_codes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("config_version", sa.Text(), nullable=False),
        sa.Column("decider_model", sa.Text(), nullable=True),
        sa.Column("decider_checkpoint", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("band", sa.Text(), nullable=True),
        sa.Column("nature", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("reconciled", sa.Boolean(), nullable=False),
        sa.Column("nature_probabilities", JSON, nullable=False),
        sa.Column("response_probabilities", JSON, nullable=False),
        sa.Column("order_sensitivity", sa.Float(), nullable=False),
        sa.Column("rules_fired", JSON, nullable=False),
        sa.Column("receipt", JSON, nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["review_cases.id"], name=op.f("fk_analysis_runs_case_id_review_cases")
        ),
        sa.ForeignKeyConstraint(
            ["config_version"],
            ["community_configs.version"],
            name=op.f("fk_analysis_runs_config_version_community_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_analysis_runs_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["evidence_snapshots.id"],
            name=op.f("fk_analysis_runs_snapshot_id_evidence_snapshots"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
    )
    op.create_index(
        "ix_analysis_runs_case", "analysis_runs", ["case_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["review_cases.id"], name=op.f("fk_audit_events_case_id_review_cases")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_audit_events_session_id_sessions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_case", "audit_events", ["case_id", "id"])

    op.create_table(
        "drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("response_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("greeting", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("closing", sa.Text(), nullable=False),
        sa.Column("cited_evidence_ids", JSON, nullable=False),
        sa.Column("validation", JSON, nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("config_version", sa.Text(), nullable=False),
        sa.Column("usage", JSON, nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["review_cases.id"], name=op.f("fk_drafts_case_id_review_cases")
        ),
        sa.ForeignKeyConstraint(
            ["config_version"],
            ["community_configs.version"],
            name=op.f("fk_drafts_config_version_community_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["analysis_runs.id"], name=op.f("fk_drafts_run_id_analysis_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drafts")),
    )
    op.create_index(
        "ix_drafts_run", "drafts", ["run_id", "response_type", sa.text("created_at DESC")]
    )

    op.create_table(
        "human_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("run_id_seen", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("reviewer_display", sa.Text(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("response_type", sa.Text(), nullable=True),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["review_cases.id"], name=op.f("fk_human_outcomes_case_id_review_cases")
        ),
        sa.ForeignKeyConstraint(
            ["run_id_seen"],
            ["analysis_runs.id"],
            name=op.f("fk_human_outcomes_run_id_seen_analysis_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_human_outcomes_session_id_sessions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_human_outcomes")),
    )
    op.create_index(
        "ix_human_outcomes_case", "human_outcomes", ["case_id", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_human_outcomes_history", "human_outcomes", ["created_at", "reviewer_display"]
    )


def downgrade() -> None:
    for table in (
        "human_outcomes",
        "drafts",
        "audit_events",
        "analysis_runs",
        "sessions",
        "jobs",
        "evidence_snapshots",
        "review_cases",
        "invite_codes",
        "community_configs",
    ):
        op.drop_table(table)

"""workspaces, invite revocation, workspace id on the main tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19

Additive. One default workspace is seeded from the home page's own wording. `workspace_id` is a
plain nullable column on the six tables below (NULL means the default workspace): SQLite adds a
nullable column in place, whereas a foreign key would force a rebuild of tables whose indexes the
migrations take care to keep. Invites gain `revoked_at` and `created_by`.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SCOPED_TABLES = (
    "invite_codes",
    "review_cases",
    "analysis_runs",
    "drafts",
    "human_outcomes",
    "audit_events",
)


def upgrade() -> None:
    workspaces = op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tagline", sa.Text(), nullable=False),
        sa.Column("accent_hex", sa.Text(), nullable=False),
        sa.Column("logo_svg", sa.Text(), nullable=True),
        sa.Column("community_paragraph", sa.Text(), nullable=False),
        sa.Column("active_pack", sa.Text(), nullable=True),
        sa.Column("lane_thresholds", JSON, nullable=True),
        sa.Column("calibration_version", sa.Text(), nullable=True),
        sa.Column("osm_signin_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
    now = datetime.now(UTC)
    op.bulk_insert(
        workspaces,
        [
            {
                "id": DEFAULT_ID,
                "slug": "default",
                "name": "Changeset Second Opinion",
                "tagline": "Evidence first; a human posts.",
                "accent_hex": "#4E5BD8",
                "logo_svg": None,
                "community_paragraph": (
                    "A community can pick a pack of settings, such as a more welcoming one for "
                    "newcomers or a stricter one, and tune the cut points from its own reviewers' "
                    "decisions. Nothing applies by itself, and every receipt names the version it "
                    "ran with."
                ),
                "active_pack": "default",
                "lane_thresholds": None,
                "calibration_version": None,
                "osm_signin_enabled": True,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
        ],
    )
    for table in SCOPED_TABLES:
        op.add_column(table, sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.add_column(
        "invite_codes", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("invite_codes", sa.Column("created_by", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invite_codes") as batch:
        batch.drop_column("created_by")
        batch.drop_column("revoked_at")
    for table in SCOPED_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("workspace_id")
    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
    # batch rebuilds on SQLite reflect indexes without their DESC part; put those back
    desc = sa.text("created_at DESC")
    restored: tuple[tuple[str, str, list[str | sa.TextClause]], ...] = (
        ("ix_human_outcomes_case", "human_outcomes", ["case_id", desc]),
        ("ix_analysis_runs_case", "analysis_runs", ["case_id", desc]),
        ("ix_drafts_run", "drafts", ["run_id", "response_type", desc]),
        ("ix_review_cases_queue", "review_cases", ["lane_rank", desc, "id"]),
        ("ix_review_cases_status", "review_cases", ["status", desc]),
    )
    for name, table, columns in restored:
        op.drop_index(name, table_name=table, if_exists=True)
        op.create_index(name, table, columns)

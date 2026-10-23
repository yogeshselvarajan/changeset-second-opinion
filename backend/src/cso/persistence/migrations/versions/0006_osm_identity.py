"""identities, pending OSM sign-ins, identity on sessions and outcomes

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19

Additive, with one relaxation: `sessions.invite_code_id` becomes nullable because a session opened
by signing in with OpenStreetMap has no invite code. Existing rows are untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _restore_desc_index() -> None:
    """SQLite rebuilds the table in batch mode and reflects the index without its DESC part."""
    op.drop_index("ix_human_outcomes_case", table_name="human_outcomes", if_exists=True)
    op.create_index(
        "ix_human_outcomes_case", "human_outcomes", ["case_id", sa.text("created_at DESC")]
    )


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("osm_uid", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("account_created", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_identities_osm_uid", "identities", ["osm_uid"], unique=True)
    op.create_table(
        "oauth_states",
        sa.Column("state_hash", sa.Text(), primary_key=True),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("sessions") as batch:
        batch.alter_column("invite_code_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(
            sa.Column(
                "identity_id",
                sa.Uuid(),
                sa.ForeignKey("identities.id", name="fk_sessions_identity_id"),
                nullable=True,
            )
        )
    with op.batch_alter_table("human_outcomes") as batch:
        batch.add_column(
            sa.Column(
                "identity_id",
                sa.Uuid(),
                sa.ForeignKey("identities.id", name="fk_human_outcomes_identity_id"),
                nullable=True,
            )
        )
    _restore_desc_index()


def downgrade() -> None:
    with op.batch_alter_table("human_outcomes") as batch:
        batch.drop_column("identity_id")
    _restore_desc_index()
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("identity_id")
        batch.alter_column("invite_code_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_table("oauth_states")
    op.drop_index("ix_identities_osm_uid", table_name="identities")
    op.drop_table("identities")

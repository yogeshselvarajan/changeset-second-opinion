"""calibrations table, probe corrections on outcomes, calibration id on config versions

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19

Additive only. Outcomes recorded before keep NULL probe corrections, config versions stored before
keep a NULL calibration id.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calibrations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("pack_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n_outcomes", sa.Integer(), nullable=False),
        sa.Column("thresholds", JSON, nullable=False),
        sa.Column("band_report", JSON, nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
    )
    with op.batch_alter_table("community_configs") as batch:
        batch.add_column(sa.Column("calibration_id", sa.Text(), nullable=True))
    with op.batch_alter_table("human_outcomes") as batch:
        batch.add_column(sa.Column("probe_corrections", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("human_outcomes") as batch:
        batch.drop_column("probe_corrections")
    with op.batch_alter_table("community_configs") as batch:
        batch.drop_column("calibration_id")
    op.drop_table("calibrations")

"""community_configs.pack_id: which community pack a stored configuration version belongs to

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19

Additive only. Versions stored before packs existed keep NULL, which the API reads as the id inside
the stored YAML.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("community_configs") as batch:
        batch.add_column(sa.Column("pack_id", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("community_configs") as batch:
        batch.drop_column("pack_id")

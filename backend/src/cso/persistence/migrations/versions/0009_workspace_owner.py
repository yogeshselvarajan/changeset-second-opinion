"""the account that claimed the workspace

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19

Additive. A fresh workspace has no owner; the first person signed in with OpenStreetMap can claim
it in the web app. The column is a plain nullable id (no foreign key, like `workspace_id` on the
other tables) so SQLite adds it in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("owner_identity_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("owner_identity_id")

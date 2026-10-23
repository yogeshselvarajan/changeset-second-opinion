"""jobs.request_id: the API request that queued a job, so logs correlate across the worker

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17

Additive only. Existing jobs keep NULL, which the worker treats as "no request id".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("request_id", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("request_id")

"""the mapper's changeset comment on each queue row

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-20

Additive. A short copy of the changeset comment is kept on the case so the queue can show what the
mapper said they did, in their words, without opening every case. Existing rows stay empty until
their next snapshot.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_cases", sa.Column("comment", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("review_cases") as batch:
        batch.drop_column("comment")
